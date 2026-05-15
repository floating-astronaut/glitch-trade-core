"""
Apex Trader Funding — Drawdown Zero (futures-style trailing) rule set.

Sourced 2026-05-15 from
  https://apextraderfunding.com/rules
  https://propfirmmatch.com/apex-rules

Apex is futures-first, but their rule structure has migrated into
Forex prop-firm copy ("Drawdown Zero"). We model the trailing-stop
variant: drawdown trails the equity high until profits hit the
end-of-day cushion, then locks at starting balance.

Distinct mechanic vs FundingPips:
  - Trailing tracks INTRADAY equity, not just end-of-day, so a
    spike-and-revert on the same day eats your buffer and doesn't
    reset
  - Buffer = trailing_threshold; once profits clear `lock_at_pct`,
    drawdown floor LOCKS at starting_balance and stops trailing

For v1 we approximate with `drawdown_is_static = False` (i.e.
trail from HWM behaviour like FundingPips Zero), and add the
`drawdown_lock_at_pct` field that the simulator can honour later
once we model intraday equity properly.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApexDrawdownZeroRules:
    # ── Hard breaches (account immediately failed) ──────────────────────
    max_daily_loss_pct: float = 0.0             # Apex doesn't have a daily cap
    max_trailing_dd_pct: float = 0.03           # 3 % trailing buffer

    # ── Payout / progression rules ──────────────────────────────────────
    profit_cushion_pct: float = 0.0
    min_withdraw_total_pct: float = 0.06        # 6 % to first payout
    drawdown_lock_at_pct: float = 0.06          # trail locks at +6 % profit

    # ── Consistency & activity ──────────────────────────────────────────
    max_best_day_share_of_profit: float = 0.30  # best day ≤ 30 % of total
    min_profitable_days_per_30: int = 0
    min_profitable_day_pct: float = 0.0
    min_trades_per_30_days: int = 7             # min 7 trading days

    # ── Trading restrictions ────────────────────────────────────────────
    hold_over_weekend: bool = False             # flat by close on Fri
    block_minutes_around_news: int = 0          # not enforced

    # ── Economic terms (reporting only) ─────────────────────────────────
    profit_split_to_trader: float = 0.90        # 100% on first $25k, then 90%
    payout_cadence_days: int = 8                # bi-weekly first, daily after
    account_size_options_usd: tuple[int, ...] = (25_000, 50_000, 100_000,
                                                  150_000, 250_000, 300_000)

    # ── Simulator overlay knobs ─────────────────────────────────────────
    risk_per_trade_pct: float = 0.004           # tighter due to no daily cap
    risk_per_trade_pct_hard_cap: float = 0.008
    soft_halt_daily_loss_pct: float = 0.025     # custom halt (no firm rule)

    # ── Trailing DD: trails HWM until lock_at_pct, then locks at start ──
    drawdown_is_static: bool = False

    name: str = field(default="Apex Trader Funding — Drawdown Zero")


APEX_DRAWDOWN_ZERO = ApexDrawdownZeroRules()
