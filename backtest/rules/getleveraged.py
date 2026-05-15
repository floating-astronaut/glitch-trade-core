"""
GetLeveraged — Turbo challenge rule set.

Sourced 2026-05-15 from operator's $5 GetLeveraged Turbo Simulation
challenge — confirmed from the welcome / objectives page after sign-up
(verbatim copy in commit message). Account label "Leveraged —
Simulation Turbo — Tejas Karan Agrawal", login 180343, server
GetLeveraged-Trade, working capital $50,000, leverage 30x.

Marketing positioning ("Pass first. Pay later. One phase. Unlimited
time."):
  - One-phase evaluation, no time limit, no minimum trading days
  - Fee deferred — only charged after passing
  - Payouts: Revolut / VISA / Mastercard / wire / crypto

What that means for the simulator: the rule set is structurally close
to FundingPips Zero (trailing DD, no min trading days) but with
slightly looser daily floor (3% vs FP-Zero's 3% — same actually) and
lower target (6% vs FP-Zero's 4% withdraw floor — actually higher).
The unlimited time + no min days means the simulator's
min_trades_per_30_days check is purely informational — there's no
firm-imposed clock.

Key structural choice: **drawdown_is_static = False** (trailing).
This is the hard one — every 1% of profit tightens the breach buffer
because the trailing reference ratchets up with HWM. Plan
strategies accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GetLeveragedTurboRules:
    # ── Hard breaches (account immediately failed) ──────────────────────
    max_daily_loss_pct: float = 0.03            # 3 % of day-open balance (verbatim from T&Cs)
    max_trailing_dd_pct: float = 0.06           # 6 % TRAILING off equity HWM (verbatim from T&Cs)

    # ── Payout / progression rules ──────────────────────────────────────
    profit_cushion_pct: float = 0.0
    min_withdraw_total_pct: float = 0.06        # 6 % profit target to pass (verbatim from T&Cs)

    # ── Consistency & activity (T&Cs explicitly say "no min trading days") ─
    max_best_day_share_of_profit: float = 1.0   # not enforced
    min_profitable_days_per_30: int = 0
    min_profitable_day_pct: float = 0.0
    min_trades_per_30_days: int = 0             # T&Cs: "Minimum Trading Days: 0"

    # ── Trading restrictions ────────────────────────────────────────────
    hold_over_weekend: bool = True              # turbo allows; verify if exotic asset restrictions apply
    block_minutes_around_news: int = 0          # not enforced on turbo

    # ── Economic terms (reporting only) ─────────────────────────────────
    profit_split_to_trader: float = 0.80
    payout_cadence_days: int = 14
    account_size_options_usd: tuple[int, ...] = (5_000, 10_000, 25_000, 50_000,
                                                  100_000, 200_000)

    # ── Simulator overlay knobs (same shape as other rule sets) ─────────
    risk_per_trade_pct: float = 0.005
    risk_per_trade_pct_hard_cap: float = 0.01
    soft_halt_daily_loss_pct: float = 0.02      # halt 1 % before 3 % breach

    # ── TRAILING DD off equity HWM (NOT static) ─────────────────────────
    # Same posture as FundingPips Zero — every 1% of profit tightens the
    # breach buffer. Test strategies expecting this.
    drawdown_is_static: bool = False

    name: str = field(default="GetLeveraged — Turbo Simulation")


GETLEVERAGED_TURBO = GetLeveragedTurboRules()
