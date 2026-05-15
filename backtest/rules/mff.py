"""
MyForexFunds (MFF) — Evaluation (Phase 1) rule set.

Sourced 2026-05-15 from
  https://myforexfunds.com/evaluation-program/
  https://propfirmmatch.com/myforexfunds-rules

Phase 1 is the entry gate; Phase 2 has the same DD limits but a
lower 5% profit target. We model Phase 1 since the harder profit
target is what selects whether the engine has the edge to even
enter MFF's funnel.

Contrast vs the other firms in our simulator:

                           MFF Eval P1    FundingPips Zero    FTMO P1
    Max overall drawdown   8% STATIC      5% TRAILING         10% STATIC
    Max daily loss         5%             3%                  5%
    Profit target to pass  8%             4% (withdraw floor) 10%
    Min trading days       5              n/a                 0
    Weekend hold           allowed        flat by Friday      allowed
    News blackout          ±2 min         ±10 min             not enforced

The 8% static DD measured off starting balance gives more headroom
than FundingPips Zero's 5% trailing. Easier than FTMO Phase 1's 10%
target, harder on consistency than FTMO.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MFFEvaluationRules:
    # ── Hard breaches (account immediately failed) ──────────────────────
    max_daily_loss_pct: float = 0.05            # 5 % of day-open balance
    max_trailing_dd_pct: float = 0.08           # 8 % static off starting

    # ── Payout / progression rules ──────────────────────────────────────
    profit_cushion_pct: float = 0.0
    min_withdraw_total_pct: float = 0.08        # need 8 % to pass Phase 1

    # ── Consistency & activity ──────────────────────────────────────────
    max_best_day_share_of_profit: float = 1.0   # not enforced on eval
    min_profitable_days_per_30: int = 0
    min_profitable_day_pct: float = 0.0
    min_trades_per_30_days: int = 5             # min 5 trading days

    # ── Trading restrictions ────────────────────────────────────────────
    hold_over_weekend: bool = True              # MFF allows
    block_minutes_around_news: int = 2          # ±2 min around high-impact

    # ── Economic terms (reporting only) ─────────────────────────────────
    profit_split_to_trader: float = 0.85
    payout_cadence_days: int = 14
    account_size_options_usd: tuple[int, ...] = (10_000, 25_000, 50_000,
                                                  100_000, 200_000, 300_000)

    # ── Simulator overlay knobs (same shape as other rule sets) ─────────
    risk_per_trade_pct: float = 0.005
    risk_per_trade_pct_hard_cap: float = 0.01
    soft_halt_daily_loss_pct: float = 0.04      # halt 1 % before 5 % breach

    # ── Static-DD flag (8% measured from starting balance, not HWM) ─────
    drawdown_is_static: bool = True

    name: str = field(default="MyForexFunds Evaluation — Phase 1")


MFF_EVALUATION = MFFEvaluationRules()
