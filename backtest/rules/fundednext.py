"""
FundedNext — Stellar Evaluation rule set.

Source: https://fundednext.com/  (Stellar model, current as of 2026-06).
Values here are kept in lock-step with the API-side firm catalogue
(`api/src/glitch_trade_api/firm_catalogue.py`, firm id "fundednext")
so the simulator-vs-detector "moat" test cross-checks cleanly.

Contrast with the firms we already model:

                              FundedNext      FTMO Phase 1   FundingPips Zero
    Max overall drawdown      8 % STATIC      10 % STATIC    5 % TRAILING
    Max daily loss            5 %             5 %            3 %
    Withdraw floor to pass    5 %             10 %           4 %
    Min profitable days       0               0              7 / 30
    Best-day consistency      none enforced   none           <= 15 % of profit
    Weekend hold              allowed         allowed (Plus) flat by Friday
    News blackout             not enforced    not enforced   +/-10 min hi-impact

The 8 % static-from-starting-balance drawdown sits between FundingPips
Zero's punishing 5 % trail and FTMO's roomy 10 % static. Because it is
static (pinned to the original balance, not the rolling equity HWM), a
winning streak does NOT tighten the breach buffer — the same unlock that
makes FTMO tractable applies here, just with 2 % less headroom.

Notes
-----
- Daily loss is measured against the day-open balance, same definition as
  the other rule sets (close enough for backtest purposes).
- Simulator-overlay knobs (`risk_per_trade_pct`, `soft_halt_daily_loss_pct`)
  keep the FundingPips/FTMO shape so HPO doesn't see a new parameter space.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FundedNextEvaluationRules:
    # -- Hard breaches (account immediately failed) ----------------------
    max_daily_loss_pct: float = 0.05            # 5 % of day-open balance
    max_trailing_dd_pct: float = 0.08           # 8 %, interpreted as static-
                                                # from-starting via the flag
                                                # below (see VirtualAccount).

    # -- Payout / progression rules --------------------------------------
    profit_cushion_pct: float = 0.0             # no withdraw cushion
    min_withdraw_total_pct: float = 0.05        # need 5 % to clear evaluation

    # -- Consistency & activity (FundedNext doesn't enforce these) -------
    max_best_day_share_of_profit: float = 1.0   # disabled
    min_profitable_days_per_30: int = 0
    min_profitable_day_pct: float = 0.0
    min_trades_per_30_days: int = 1

    # -- Trading restrictions --------------------------------------------
    hold_over_weekend: bool = True
    block_minutes_around_news: int = 0          # not enforced

    # -- Economic terms (reporting only) ---------------------------------
    profit_split_to_trader: float = 0.80        # 80 % to trader (up to 95 %)
    payout_cadence_days: int = 14
    account_size_options_usd: tuple[int, ...] = (6_000, 15_000, 25_000,
                                                 50_000, 100_000, 200_000)

    # -- Simulator overlay knobs (same shape as the other rule sets) -----
    risk_per_trade_pct: float = 0.005
    risk_per_trade_pct_hard_cap: float = 0.01
    soft_halt_daily_loss_pct: float = 0.04      # halt 1 % before 5 % breach

    # -- Static-DD flag (simulator pins DD reference to starting balance) -
    # FundedNext's 8 % is measured off the ORIGINAL starting balance, not
    # the rolling equity HWM. The simulator reads this flag to disable the
    # HWM ratchet for this rule set (identical treatment to FTMO).
    drawdown_is_static: bool = True

    name: str = field(default="FundedNext — Stellar Evaluation")


FUNDEDNEXT_EVALUATION = FundedNextEvaluationRules()
