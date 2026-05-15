"""
FTMO Challenge — Phase 1 rule set.

Source: https://ftmo.com/en/trading-objectives/  (current as of 2026-05).
Phase 1 is the entry gate; once cleared the trader proceeds to Phase 2
(same 10 % overall DD, 5 % daily, but 5 % profit target). For backtest
realism we always model Phase 1 since the harder profit target is what
selects whether the engine has enough edge to enter the FTMO funnel at
all.

Critical contrast with FundingPips Zero (the rule set we currently
fail on):

                              FTMO Phase 1   FundingPips Zero
    Max overall drawdown      10 % STATIC    5 % TRAILING
    Max daily loss            5 %            3 %
    Profit target to pass     10 %           4 %  (withdraw floor)
    Min trading days          0              n/a
    Min profitable days       0              7 / 30
    Best-day consistency      none enforced  ≤ 15 % of total profit
    Weekend hold              allowed (Plus) flat by Friday close
    News blackout             not enforced   ±10 min high-impact

The static-not-trailing 10 % DD is the big unlock. With FundingPips
Zero, every 1 % equity gain tightens our breach buffer because the
HWM ratchets up. FTMO's static 10 % off the *original starting
balance* gives strategies room to mean-revert after a winning streak
without immediately blowing up on the next normal loss.

Notes
-----
- FTMO measures the daily loss against the day-open *balance* (not
  end-of-day equity); we use the same definition as FundingPips Zero
  for now, which is close enough for backtest purposes.
- We keep the simulator-overlay knobs (`risk_per_trade_pct`,
  `soft_halt_daily_loss_pct`) in the same shape as the FundingPips
  rule set so HPO doesn't have to learn a new parameter space.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FTMOChallengeRules:
    # ── Hard breaches (account immediately failed) ──────────────────────
    max_daily_loss_pct: float = 0.05            # 5 % of day-open balance
    max_trailing_dd_pct: float = 0.10           # interpreted as static-from-
                                                 # starting; see VirtualAccount
                                                 # below — we patch the meaning
                                                 # at the simulator level.

    # ── Payout / progression rules ──────────────────────────────────────
    profit_cushion_pct: float = 0.0             # FTMO has no withdraw cushion
    min_withdraw_total_pct: float = 0.10        # need 10 % to pass Phase 1

    # ── Consistency & activity (FTMO doesn't enforce these on Phase 1) ─
    max_best_day_share_of_profit: float = 1.0   # disabled
    min_profitable_days_per_30: int = 0
    min_profitable_day_pct: float = 0.0
    min_trades_per_30_days: int = 1

    # ── Trading restrictions ────────────────────────────────────────────
    hold_over_weekend: bool = True              # FTMO Plus allows it; default
    block_minutes_around_news: int = 0          # not enforced

    # ── Economic terms (reporting only) ─────────────────────────────────
    profit_split_to_trader: float = 0.80        # 90% with FTMO Plus add-on
    payout_cadence_days: int = 14
    account_size_options_usd: tuple[int, ...] = (10_000, 25_000, 50_000,
                                                  100_000, 200_000)

    # ── Simulator overlay knobs (same shape as FundingPips Zero) ────────
    risk_per_trade_pct: float = 0.005
    risk_per_trade_pct_hard_cap: float = 0.01
    soft_halt_daily_loss_pct: float = 0.04      # halt 1 % before 5 % breach

    # ── Static-DD flag (the simulator switches drawdown reference accordingly) ─
    # FTMO's 10 % is measured off the ORIGINAL starting balance, NOT off
    # the rolling equity HWM. The simulator's `account.py` ordinarily
    # ratchets the HWM up as profit accrues; for FTMO we want to pin
    # the DD reference at starting_balance forever. The simulator reads
    # this flag to decide which behaviour to use.
    drawdown_is_static: bool = True

    name: str = field(default="FTMO Challenge — Phase 1")


FTMO_CHALLENGE = FTMOChallengeRules()
