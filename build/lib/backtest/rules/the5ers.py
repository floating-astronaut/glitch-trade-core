"""
The5ers — High Stakes Challenge rule set.

Sourced 2026-05-15 from
  https://www.the5ers.com/high-stakes-challenge/
  https://propfirmmatch.com/the5ers-rules

The5ers is the conservative end of the spectrum: tightest daily
loss (4%), modest profit target (8%), but generous static DD (4%
of starting balance — the strictest in our roster) and a 6%
profit-cushion before payouts unlock.

Notable: 1% daily floor on consistency days (high signal-to-noise
filter — many small-PNL days don't count toward the 5-day minimum).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class The5ersHighStakesRules:
    # ── Hard breaches (account immediately failed) ──────────────────────
    max_daily_loss_pct: float = 0.04            # 4 % of day-open balance
    max_trailing_dd_pct: float = 0.04           # 4 % static off starting

    # ── Payout / progression rules ──────────────────────────────────────
    profit_cushion_pct: float = 0.06            # first 6 % locked
    min_withdraw_total_pct: float = 0.08        # need 8 % to pass

    # ── Consistency & activity ──────────────────────────────────────────
    max_best_day_share_of_profit: float = 0.50  # best day ≤ 50 % of total
    min_profitable_days_per_30: int = 5
    min_profitable_day_pct: float = 0.01        # 1 % min for a day to count
    min_trades_per_30_days: int = 5

    # ── Trading restrictions ────────────────────────────────────────────
    hold_over_weekend: bool = True
    block_minutes_around_news: int = 5

    # ── Economic terms (reporting only) ─────────────────────────────────
    profit_split_to_trader: float = 0.80
    payout_cadence_days: int = 30
    account_size_options_usd: tuple[int, ...] = (5_000, 20_000, 100_000)

    # ── Simulator overlay knobs ─────────────────────────────────────────
    risk_per_trade_pct: float = 0.004
    risk_per_trade_pct_hard_cap: float = 0.008
    soft_halt_daily_loss_pct: float = 0.03      # 1 % buffer before 4 % breach

    # ── Static DD off starting balance ──────────────────────────────────
    drawdown_is_static: bool = True

    name: str = field(default="The5ers High Stakes Challenge")


THE5ERS_HIGH_STAKES = The5ersHighStakesRules()
