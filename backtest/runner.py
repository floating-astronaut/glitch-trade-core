"""
Tape-replay runner.

Reads closed trades from `ml_trades`, chronologically, scales each trade's
$-risk to the prop-firm rule set, applies it to a `VirtualAccount`, and
returns the run state for reporting.

This is *not* a fresh strategy simulator — it uses the historical PnL the
live engine actually realised. What it tells you is:

    "If FundingPips had been the broker and we had risk-sized every trade
     to 0.5 % of the account, would the engine have survived, and how
     much would it have made?"

For per-bot 'what if we'd disabled X' analysis, pass `include_bots=` /
`exclude_bots=`. For per-symbol filtering pass `include_symbols=`.

Usage
-----
    from backtest.runner import run_tape_replay
    result = run_tape_replay(
        starting_balance=25_000,
        date_from='2026-04-15',
        date_to='2026-05-13',
        exclude_bots={'viper', 'anaconda', 'cobra'},
    )
    print(result.summary)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

import psycopg2
from psycopg2.extras import RealDictCursor

from .account import VirtualAccount, Breach, DailyRecord
from .rules import FundingPipsZeroRules, FUNDINGPIPS_ZERO
from .sizer import scale_trade, SizingResult


def _ml_dsn() -> str:
    """Pick a DSN that works from this box.

    Order:
      1. ML_DATABASE_URL (used by admin_api container)
      2. local Postgres on the unix socket (the host-side `glitchml_ro` role)
    """
    dsn = os.environ.get("ML_DATABASE_URL")
    if dsn:
        return dsn
    # Fallback for ad-hoc runs from the host.
    return "postgresql://glitchml_ro@/glitch_ml?host=/var/run/postgresql"


@dataclass
class SimTrade:
    """One historical trade after sizing — what the simulator booked."""
    opened_at: datetime
    closed_at: datetime
    bot: str
    symbol: str
    raw_pnl: float
    scaled_pnl: float
    scale: float
    capped: bool
    vetoed: Optional[str] = None  # reason if the trade wasn't allowed


@dataclass
class RunResult:
    account: VirtualAccount
    trades: list[SimTrade] = field(default_factory=list)
    vetoed: list[SimTrade] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        s = self.account.summary()
        s.update({
            "trades_applied": sum(1 for t in self.trades if t.vetoed is None),
            "trades_vetoed":  len(self.vetoed),
            "trades_capped":  sum(1 for t in self.trades if t.capped),
        })
        return s


# ── Trade fetch ─────────────────────────────────────────────────────────

_TRADE_SQL = """
SELECT t.id, t.opened_at, t.closed_at, t.bot_name AS bot, t.symbol,
       t.entry_price, t.sl, t.lot_size AS lots, t.pnl AS realised_pnl,
       t.outcome, t.exit_reason
FROM ml_trades t
WHERE t.closed_at IS NOT NULL
  AND ({date_from}::timestamptz IS NULL OR t.opened_at >= {date_from})
  AND ({date_to}::timestamptz   IS NULL OR t.opened_at <  {date_to})
  AND ({bot_filter} OR t.bot_name = ANY(%(bots)s))
  AND ({symbol_filter} OR t.symbol = ANY(%(symbols)s))
ORDER BY t.opened_at ASC, t.id ASC
"""


def _fetch_trades(
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    include_bots: Optional[Sequence[str]],
    exclude_bots: Optional[Sequence[str]],
    include_symbols: Optional[Sequence[str]],
) -> list[dict]:
    """Pull the tape from ml_trades, honouring the filters."""
    where = ["t.closed_at IS NOT NULL"]
    params: dict = {}

    if date_from:
        where.append("t.opened_at >= %(date_from)s")
        params["date_from"] = date_from
    if date_to:
        where.append("t.opened_at < %(date_to)s")
        params["date_to"] = date_to

    if include_bots:
        where.append("t.bot_name = ANY(%(bots_in)s)")
        params["bots_in"] = list(include_bots)
    if exclude_bots:
        where.append("NOT (t.bot_name = ANY(%(bots_ex)s))")
        params["bots_ex"] = list(exclude_bots)
    if include_symbols:
        where.append("t.symbol = ANY(%(symbols_in)s)")
        params["symbols_in"] = list(include_symbols)

    sql = f"""
        SELECT t.id, t.opened_at, t.closed_at, t.bot_name AS bot, t.symbol,
               t.entry_price, t.sl_price AS sl, t.volume_lots AS lots,
               t.pnl AS realised_pnl, t.outcome, t.exit_reason
        FROM ml_trades t
        WHERE {' AND '.join(where)}
        ORDER BY t.opened_at ASC, t.id ASC
    """
    conn = psycopg2.connect(_ml_dsn(), cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


# ── Main loop ───────────────────────────────────────────────────────────

def run_tape_replay(
    *,
    starting_balance: float = 25_000,
    rules: FundingPipsZeroRules = FUNDINGPIPS_ZERO,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_bots: Optional[Iterable[str]] = None,
    exclude_bots: Optional[Iterable[str]] = None,
    include_symbols: Optional[Iterable[str]] = None,
) -> RunResult:
    """Replay the historical trade tape and report what would have happened."""
    rows = _fetch_trades(
        date_from=date_from,
        date_to=date_to,
        include_bots=list(include_bots) if include_bots else None,
        exclude_bots=list(exclude_bots) if exclude_bots else None,
        include_symbols=list(include_symbols) if include_symbols else None,
    )

    if not rows:
        # Empty input — return a clean dead account.
        acc = VirtualAccount(starting_balance, rules)
        return RunResult(account=acc, trades=[], vetoed=[])

    start_ts = rows[0]["opened_at"].astimezone(timezone.utc)
    acc = VirtualAccount(starting_balance, rules, start_ts=start_ts)
    out = RunResult(account=acc, trades=[], vetoed=[])

    for r in rows:
        if acc.terminated:
            break

        opened_at: datetime = r["opened_at"].astimezone(timezone.utc)
        closed_at: datetime = r["closed_at"].astimezone(timezone.utc)
        symbol = r["symbol"]
        bot = r["bot"]
        raw_pnl = float(r["realised_pnl"] or 0)

        # 1) Soft-halt check at intended open time.
        veto = acc.before_open(opened_at)
        if veto is not None:
            out.vetoed.append(
                SimTrade(
                    opened_at=opened_at, closed_at=closed_at,
                    bot=bot, symbol=symbol,
                    raw_pnl=raw_pnl, scaled_pnl=0.0, scale=0.0,
                    capped=False, vetoed=veto,
                )
            )
            continue

        # 2) Risk-aware sizing.
        #    Cap sizing base at min(starting, current). Once we're above
        #    starting, we don't want bigger trades — the trailing-DD buffer
        #    is what constrains us, not absolute equity.
        sizing_base = min(acc.starting_balance, acc.balance)
        sized: SizingResult = scale_trade(
            balance=acc.balance,
            realised_pnl=raw_pnl,
            symbol=symbol,
            entry=float(r["entry_price"]) if r.get("entry_price") is not None else None,
            sl=float(r["sl"]) if r.get("sl") is not None else None,
            lots=float(r["lots"]) if r.get("lots") is not None else None,
            rules=rules,
            sizing_base=sizing_base,
        )

        # 3) Apply at close time (we don't model intra-trade equity in mode A).
        acc.record_close(closed_at, sized.scaled_pnl)
        out.trades.append(
            SimTrade(
                opened_at=opened_at, closed_at=closed_at,
                bot=bot, symbol=symbol,
                raw_pnl=raw_pnl, scaled_pnl=sized.scaled_pnl,
                scale=sized.scale, capped=sized.capped,
            )
        )

    # Final day rollup
    if not acc.terminated and rows:
        acc.roll_day(rows[-1]["closed_at"].astimezone(timezone.utc))

    return out
