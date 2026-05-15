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
    soft_halt_daily_loss_pct: float = 0.02      # halt trading at -2 % day
                                                # (1 % buffer before 3 % breach)

    # Cached display name
    name: str = field(default="FundingPips Zero (instant-funded)")


# Default singleton; import as `from backtest.rules import FUNDINGPIPS_ZERO`.
FUNDINGPIPS_ZERO = FundingPipsZeroRules()
