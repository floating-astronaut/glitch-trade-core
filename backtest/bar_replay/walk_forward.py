"""
Walk-forward validation for HPO winners.

A 200-trial sweep on a 30-day window will inevitably surface configs
that look amazing on training data but fail out-of-sample — pure
overfit. Walk-forward catches that:

  1. Split the available bars into train + test (default 70/30).
  2. Run an Optuna sweep on train only.
  3. Take the top-K configs and re-evaluate them on test.
  4. Report:
       - the train↔test PnL gap per config
       - the "still passes on test?" verdict
       - the most robust config = highest test PnL among passers

A config that wins on train and survives test is real signal. A config
that wins on train but breaches on test is noise.

CLI:

    python -m backtest.bar_replay.walk_forward --symbol JPN225 --trials 300
    python -m backtest.bar_replay.walk_forward --symbol JPN225 --train-frac 0.70 \\
                                                --topk 10 --out winners.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import optuna
from optuna.samplers import TPESampler

from .bars import BarsRequest, load_bars
from .manager import ManagerParams
from .sim import SimConfig, run_sim
from .strategy import TrendFollowerParams
from .sweep import _build_cfg, _score


def _bar_window(symbol: str, timeframe: str) -> tuple[datetime, datetime]:
    """Earliest and latest bar timestamp we have for (symbol, timeframe)."""
    bars = load_bars(BarsRequest(symbol=symbol, timeframe=timeframe))
    if bars.size == 0:
        raise SystemExit(f"no bars for {symbol} {timeframe}")
    start = bars["t"][0].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
    end   = bars["t"][-1].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
    return start, end


def _split(start: datetime, end: datetime, train_frac: float
           ) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    span = end - start
    cutoff = start + timedelta(seconds=span.total_seconds() * train_frac)
    return (start, cutoff), (cutoff, end)


def make_train_objective(symbol: str, timeframe: str,
                         train_start: datetime, train_end: datetime):
    def objective(trial: optuna.Trial) -> float:
        cfg = _build_cfg(symbol, timeframe, trial)
        # SimConfig is frozen; rebuild with the train window.
        cfg = SimConfig(
            symbol=cfg.symbol, timeframe=cfg.timeframe,
            start=train_start, end=train_end,
            starting_balance=cfg.starting_balance, rules=cfg.rules,
            strategy=cfg.strategy, manager=cfg.manager,
        )
        result = run_sim(cfg)
        for k, v in result.items():
            if k != "config":
                trial.set_user_attr(k, v)
        return _score(result)
    return objective


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="backtest.bar_replay.walk_forward")
    p.add_argument("--symbol",     required=True)
    p.add_argument("--timeframe",  default="h1")
    p.add_argument("--trials",     type=int,   default=300)
    p.add_argument("--train-frac", type=float, default=0.70)
    p.add_argument("--topk",       type=int,   default=10)
    p.add_argument("--seed",       type=int,   default=42)
    p.add_argument("--jobs",       type=int,   default=1)
    p.add_argument("--out",        help="JSON output path for validated winners")
    args = p.parse_args(argv)

    full_start, full_end = _bar_window(args.symbol, args.timeframe)
    (train_start, train_end), (test_start, test_end) = _split(
        full_start, full_end, args.train_frac
    )
    print(f"\n=== walk-forward {args.symbol} {args.timeframe} ===")
    print(f"  train: {train_start.date()} → {train_end.date()}")
    print(f"  test:  {test_start.date()} → {test_end.date()}")
    print(f"  trials on train: {args.trials}")

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=args.seed, n_startup_trials=20),
    )
    study.optimize(
        make_train_objective(args.symbol, args.timeframe, train_start, train_end),
        n_trials=args.trials,
        n_jobs=args.jobs,
        show_progress_bar=False,
    )

    # Rank training trials, take top-K, re-evaluate on test
    def _rank(t):
        a = t.user_attrs
        return (
            int(a.get("passes", False)),
            int(a.get("alive", False)),
            float(a.get("total_pnl_pct", -1.0)),
        )
    top = sorted(study.trials, key=_rank, reverse=True)[: args.topk]

    print(f"\n  re-evaluating top {len(top)} on test window…")
    rows = []
    for i, t in enumerate(top):
        # Build the manager + strategy params from this trial
        cfg = SimConfig(
            symbol=args.symbol, timeframe=args.timeframe,
            start=test_start, end=test_end,
            manager=ManagerParams(
                sl_atr_mult     = t.params["sl_atr_mult"],
                tp1_r           = t.params["tp1_r"],
                tp1_fraction    = t.params["tp1_fraction"],
                trail_step_r    = t.params["trail_step_r"],
                min_confidence  = t.params["min_confidence"],
            ),
            strategy=TrendFollowerParams(adx_min_trend=t.params["adx_min_trend"]),
        )
        test_res = run_sim(cfg)
        train_pnl = float(t.user_attrs.get("total_pnl_pct", 0))
        test_pnl  = float(test_res["total_pnl_pct"])
        rows.append({
            "rank":         i + 1,
            "params":       t.params,
            "train_passes": bool(t.user_attrs.get("passes", False)),
            "train_pnl":    train_pnl,
            "train_trades": int(t.user_attrs.get("trades", 0)),
            "test_passes":  bool(test_res["passes"]),
            "test_alive":   bool(test_res["alive"]),
            "test_pnl":     test_pnl,
            "test_trades":  int(test_res["trades"]),
            "test_breach":  test_res.get("breach"),
            "robustness":   round(test_pnl / train_pnl, 3) if train_pnl > 0 else None,
        })

    print(f"\n  {'rank':>4}  {'tr.pass':>7} {'tr.pnl%':>8} {'tr.n':>5}  "
          f"{'te.pass':>7} {'te.alive':>8} {'te.pnl%':>8} {'te.n':>5}  robust")
    for r in rows:
        print(
            f"  {r['rank']:>4}  "
            f"{('Y' if r['train_passes'] else 'N'):>7} "
            f"{r['train_pnl']*100:>7.2f}% "
            f"{r['train_trades']:>5}  "
            f"{('Y' if r['test_passes'] else 'N'):>7} "
            f"{('Y' if r['test_alive'] else 'N'):>8} "
            f"{r['test_pnl']*100:>7.2f}% "
            f"{r['test_trades']:>5}  "
            f"{r['robustness'] if r['robustness'] is not None else '—'}"
        )

    # Pick the most robust passer: alive on test AND test PnL > 0.
    robust = [r for r in rows if r["test_alive"] and r["test_pnl"] > 0]
    robust.sort(key=lambda r: (r["test_passes"], r["test_pnl"]), reverse=True)

    if robust:
        winner = robust[0]
        print(f"\n  ✅ chosen winner (rank {winner['rank']}): "
              f"train+{winner['train_pnl']*100:.2f}%  test+{winner['test_pnl']*100:.2f}%")
    else:
        winner = None
        print("\n  ⚠️  no config survived test window with positive PnL — try more trials, "
              "different train fraction, or accept this symbol isn't tradeable yet")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({
                "symbol":     args.symbol,
                "timeframe":  args.timeframe,
                "train":      [train_start.isoformat(), train_end.isoformat()],
                "test":       [test_start.isoformat(),  test_end.isoformat()],
                "trials":     args.trials,
                "top_k":      args.topk,
                "winner":     winner,
                "all":        rows,
            }, f, indent=2, default=str)
        print(f"\n  → wrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
