"""
Hyperparameter sweep — Optuna over the bar-replay simulator.

Search space (6 dims, intentionally small for v1):

  manager.sl_atr_mult          0.8 – 3.0    (continuous)
  manager.tp1_r                0.6 – 2.5    (continuous)
  manager.tp1_fraction         0.3 – 0.8    (continuous)
  manager.trail_step_r         0.3 – 1.0    (continuous)
  manager.min_confidence       0.55 – 0.85  (continuous)
  strategy.adx_min_trend       12.0 – 25.0  (continuous)

Score (composite):

  - hard reject: terminated → -1.0
  - if alive but not profitable enough: total_pnl_pct (neg/zero allowed)
  - bonus for actually passing: +0.5 floor when passes==True
  - small penalty for thin trade counts (<10 trades over the window)

Optuna's default sampler (TPE) handles continuous + categorical mixes
without ceremony.

CLI:

    python -m backtest.bar_replay.sweep --symbol JPN225 --trials 200
    python -m backtest.bar_replay.sweep --symbol JPN225 --trials 1000 --jobs 4
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

import optuna
from optuna.samplers import TPESampler

from .manager import ManagerParams
from .sim import SimConfig, run_sim
from .strategy import TrendFollowerParams


def _build_cfg(symbol: str, timeframe: str, trial: optuna.Trial) -> SimConfig:
    sl_atr_mult     = trial.suggest_float("sl_atr_mult",     0.8,  3.0)
    tp1_r           = trial.suggest_float("tp1_r",           0.6,  2.5)
    tp1_fraction    = trial.suggest_float("tp1_fraction",    0.3,  0.8)
    trail_step_r    = trial.suggest_float("trail_step_r",    0.3,  1.0)
    min_confidence  = trial.suggest_float("min_confidence",  0.55, 0.85)
    adx_min_trend   = trial.suggest_float("adx_min_trend",   12.0, 25.0)

    return SimConfig(
        symbol=symbol,
        timeframe=timeframe,
        manager=ManagerParams(
            sl_atr_mult=sl_atr_mult,
            tp1_r=tp1_r,
            tp1_fraction=tp1_fraction,
            trail_step_r=trail_step_r,
            min_confidence=min_confidence,
        ),
        strategy=TrendFollowerParams(adx_min_trend=adx_min_trend),
    )


def _score(result: dict) -> float:
    if result["terminated"]:
        return -1.0
    score = float(result["total_pnl_pct"])
    if result["passes"]:
        score = max(score, 0.04) + 0.50  # passing floor + bonus
    # Thin-tape penalty: too few trades is unreliable / overfit-prone
    if result["trades"] < 10:
        score -= 0.05
    return score


def make_objective(symbol: str, timeframe: str):
    def objective(trial: optuna.Trial) -> float:
        cfg = _build_cfg(symbol, timeframe, trial)
        result = run_sim(cfg)
        # Stash everything in user_attrs so we can post-mortem the whole study
        for k, v in result.items():
            if k != "config":
                trial.set_user_attr(k, v)
        return _score(result)
    return objective


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="backtest.bar_replay.sweep",
        description="Optuna sweep over the bar-replay sim for one symbol/timeframe.")
    p.add_argument("--symbol",    required=True)
    p.add_argument("--timeframe", default="h1")
    p.add_argument("--trials",    type=int, default=200)
    p.add_argument("--jobs",      type=int, default=1,
                   help="Parallel n_jobs for Optuna (in-process).")
    p.add_argument("--seed",      type=int, default=42)
    p.add_argument("--out",       help="Write top-K configs as JSON")
    p.add_argument("--top",       type=int, default=10)
    args = p.parse_args(argv)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=args.seed, n_startup_trials=20),
    )
    study.optimize(
        make_objective(args.symbol, args.timeframe),
        n_trials=args.trials,
        n_jobs=args.jobs,
        show_progress_bar=False,
    )

    # Rank passing trials, then alive-but-not-passing, then dead.
    def _rank(t):
        a = t.user_attrs
        return (
            int(a.get("passes", False)),
            int(a.get("alive", False)),
            float(a.get("total_pnl_pct", -1.0)),
        )
    ranked = sorted(study.trials, key=_rank, reverse=True)

    print(f"\n=== Top {min(args.top, len(ranked))} of {len(ranked)} ({args.symbol} {args.timeframe}) ===")
    print(f"  {'rank':>4}  {'pass':>4} {'pnl%':>7} {'trades':>6} {'maxDayLoss%':>11}  params")
    for i, t in enumerate(ranked[:args.top]):
        a = t.user_attrs
        print(
            f"  {i + 1:>4}  {('Y' if a.get('passes') else 'N'):>4} "
            f"{a.get('total_pnl_pct', 0) * 100:>6.2f}% "
            f"{a.get('trades', 0):>6} "
            f"{a.get('max_day_loss_pct', 0) * 100:>10.2f}%  "
            f"{json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in t.params.items()})}"
        )

    if args.out:
        out = []
        for t in ranked[:args.top]:
            out.append({
                "score": _score(t.user_attrs),
                "params": t.params,
                "metrics": dict(t.user_attrs),
            })
        with open(args.out, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\n  → wrote top {len(out)} to {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
