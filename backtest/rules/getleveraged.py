"""
GetLeveraged — Turbo challenge rule set (PROVISIONAL).

Sourced 2026-05-15 from operator's $5 GetLeveraged Turbo Simulation
challenge — account label "Leveraged — Simulation Turbo — Tejas Karan
Agrawal", login 180343, server GetLeveraged-Trade, balance $50,000,
leverage 30x.

⚠️ NUMBERS BELOW ARE INDUSTRY-STANDARD DEFAULTS FOR "TURBO" PROP
   CHALLENGES, NOT CONFIRMED FROM GETLEVERAGED'S OWN DOCS — their
   site (getleveraged.io) was unreachable from the trade-api box at
   build time. Confirm these against the live challenge dashboard
   before relying on them for breach math:

     getleveraged.io/challenge-rules   (or wherever the challenge
     T&Cs live for the Turbo variant)

   Then update this file. The rule names match every other rule set
   in this package so the simulator, sweep, and routes/firms.py all
   pick it up without further code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GetLeveragedTurboRules:
    # ── Hard breaches (account immediately failed) ──────────────────────
    max_daily_loss_pct: float = 0.04            # 4 % of day-open balance (industry standard for turbo)
    max_trailing_dd_pct: float = 0.06           # 6 % static off starting (turbo = tighter than standard)

    # ── Payout / progression rules ──────────────────────────────────────
    profit_cushion_pct: float = 0.0
    min_withdraw_total_pct: float = 0.08        # 8 % profit target to pass turbo

    # ── Consistency & activity ──────────────────────────────────────────
    max_best_day_share_of_profit: float = 1.0   # turbo variants often disable consistency rule
    min_profitable_days_per_30: int = 0
    min_profitable_day_pct: float = 0.0
    min_trades_per_30_days: int = 3             # min 3 trading days for turbo

    # ── Trading restrictions ────────────────────────────────────────────
    hold_over_weekend: bool = True              # turbo challenges typically allow
    block_minutes_around_news: int = 0          # not enforced on turbo

    # ── Economic terms (reporting only) ─────────────────────────────────
    profit_split_to_trader: float = 0.80
    payout_cadence_days: int = 14
    account_size_options_usd: tuple[int, ...] = (5_000, 10_000, 25_000, 50_000,
                                                  100_000, 200_000)

    # ── Simulator overlay knobs (same shape as other rule sets) ─────────
    risk_per_trade_pct: float = 0.005
    risk_per_trade_pct_hard_cap: float = 0.01
    soft_halt_daily_loss_pct: float = 0.03      # halt 1 % before 4 % breach

    # ── Static DD off starting balance (typical for turbo) ──────────────
    drawdown_is_static: bool = True

    name: str = field(default="GetLeveraged — Turbo Simulation")


GETLEVERAGED_TURBO = GetLeveragedTurboRules()
