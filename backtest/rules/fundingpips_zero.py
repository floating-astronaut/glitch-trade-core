"""
FundingPips ZERO — direct-funded (no evaluation) rule set.

Sourced 2026-05-13 from
  https://proptradingvibes.com/blog/fundingpips-zero-challenge
  https://proptradingvibes.com/blog/fundingpips-rules
  https://proptradingvibes.com/blog/fundingpips-payout-rules
  https://tradingfinder.com/props/funding-pips/rules/

If the firm tightens any of these (FundingPips has done so historically),
this file is the single source of truth — update here and rerun the
backtest.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FundingPipsZeroRules:
    # ── Hard breaches (account immediately terminated) ──────────────────
    max_daily_loss_pct: float = 0.03            # 3 % of day-open balance
    max_trailing_dd_pct: float = 0.05           # 5 % off highest equity
    # Trailing drawdown — pegs to running HWM, never ratchets down.
    # Sibling rule files set this explicitly (FTMO/MFF/The5ers are
    # static; Apex + GetLeveraged are also trailing). Naming this
    # explicitly here closes the field-set drift the trade-api
    # firm_catalogue audit (2026-05-20) surfaced.
    drawdown_is_static: bool = False

    # ── Payout / withdrawal rules ───────────────────────────────────────
    profit_cushion_pct: float = 0.03            # first 3 % is locked,
    min_withdraw_total_pct: float = 0.04        # need ≥ 4 % total to cash out

    # ── Consistency & activity (payout-blocking, not account-killing) ───
    max_best_day_share_of_profit: float = 0.15  # best day ≤ 15 % of total profit
    min_profitable_days_per_30: int = 7
    min_profitable_day_pct: float = 0.0025      # each counted day ≥ 0.25 %
    min_trades_per_30_days: int = 1

    # ── Trading restrictions ────────────────────────────────────────────
    hold_over_weekend: bool = False             # all positions flat by Fri close
    block_minutes_around_news: int = 10         # ±10 min around high-impact

    # ── Economic terms (reporting only) ─────────────────────────────────
    profit_split_to_trader: float = 0.95
    payout_cadence_days: int = 14
    account_size_options_usd: tuple[int, ...] = (25_000, 50_000, 100_000, 200_000)

    # ── Simulator overlay knobs (not firm-set; ours) ────────────────────
    # The live engine has never run with prop-firm-grade risk caps.
    # These are the constraints we add to keep individual trades from
    # blowing daily / trailing DD on their own.
    risk_per_trade_pct: float = 0.005           # target $-risk per trade
    risk_per_trade_pct_hard_cap: float = 0.01   # absolute ceiling
    soft_halt_daily_loss_pct: float = 0.025     # halt trading at -2.5 % day
                                                # (0.5 % buffer before 3 % breach)

    # Daily profit cap — the symmetric upside cousin of soft_halt_daily_loss_pct.
    # When day P&L reaches +X % of day-open balance, stop opening new trades
    # for the rest of the UTC day. Existing positions still close normally.
    #
    # The mechanical reason this matters on a trailing-DD firm: every winning
    # day ratchets the equity HWM upward, which permanently tightens the
    # trailing-DD floor. If you make +5 % on Monday, your account's "you-die-
    # here" line jumps from $23,750 (5 % below $25,000) to $24,937 (5 % below
    # the new $26,250 HWM) — and any normal -1 % drift on a flat Tuesday now
    # eats most of your remaining buffer. Capping daily P&L keeps HWM growth
    # gradual, which keeps the buffer wide. Also helpfully blocks the
    # consistency-rule breach (best day ≤ 15 % of total profit) — if you
    # cap at 1 % per day you can't have one day worth 71 % of total profit.
    #
    # Default 0.015 = cap daily wins at 1.5 % to prevent aggressive HWM
    # ratcheting on trailing-DD firms. Previously 0.0 (no cap) which made
    # the 5 % trailing floor tighten unrealistically fast.
    daily_profit_cap_pct: float = 0.015

    # Cached display name
    name: str = field(default="FundingPips Zero (instant-funded)")


# Default singleton; import as `from backtest.rules import FUNDINGPIPS_ZERO`.
FUNDINGPIPS_ZERO = FundingPipsZeroRules()
