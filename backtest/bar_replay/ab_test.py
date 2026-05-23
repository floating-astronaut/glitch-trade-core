"""A/B test: old FundingPips Zero rules vs. new rules.

Runs the same random configs through both rule sets and prints
termination rate, average PnL, and pass rate.
"""
from __future__ import annotations

import random
import sys
from dataclasses import replace

from backtest.bar_replay.sim import SimConfig, run_sim
from backtest.bar_replay.manager import ManagerParams
from backtest.bar_replay.strategy import TrendFollowerParams
from backtest.rules import FUNDINGPIPS_ZERO


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    symbol = sys.argv[2] if len(sys.argv) > 2 else "EURUSD"

    # Save current (new) rules
    new_rules = FUNDINGPIPS_ZERO
    # Build old rules by reverting the two changed fields
    old_rules = replace(
        new_rules,
        soft_halt_daily_loss_pct=0.02,
        daily_profit_cap_pct=0.0,
    )

    rng = random.Random(42)

    def random_cfg(rules):
        return SimConfig(
            symbol=symbol,
            timeframe="h1",
            rules=rules,
            manager=ManagerParams(
                sl_atr_mult=rng.uniform(0.8, 3.0),
                tp1_r=rng.uniform(0.6, 2.5),
                tp1_fraction=rng.uniform(0.3, 0.8),
                trail_step_r=rng.uniform(0.3, 1.0),
                min_confidence=rng.uniform(0.55, 0.85),
            ),
            strategy=TrendFollowerParams(adx_min_trend=rng.uniform(12.0, 25.0)),
        )

    old_results = []
    new_results = []

    for i in range(n):
        cfg_old = random_cfg(old_rules)
        cfg_new = random_cfg(new_rules)

        old_results.append(run_sim(cfg_old))
        new_results.append(run_sim(cfg_new))

    def summarize(label, results):
        terminated = sum(1 for r in results if r["terminated"])
        passed = sum(1 for r in results if r["passes"])
        avg_pnl = sum(r["total_pnl_pct"] for r in results) / len(results)
        avg_trades = sum(r["trades"] for r in results) / len(results)
        print(f"{label:12s} | term={terminated:3d}/{n} | pass={passed:3d}/{n} | avg_pnl={avg_pnl:+.2f}% | avg_trades={avg_trades:.1f}")

    summarize("OLD", old_results)
    summarize("NEW", new_results)

    # Detail: configs that passed under NEW but not OLD
    new_pass_old_fail = sum(
        1 for o, n in zip(old_results, new_results)
        if n["passes"] and not o["passes"]
    )
    old_pass_new_fail = sum(
        1 for o, n in zip(old_results, new_results)
        if o["passes"] and not n["passes"]
    )
    print(f"\nNEW pass / OLD fail: {new_pass_old_fail}")
    print(f"OLD pass / NEW fail: {old_pass_new_fail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
