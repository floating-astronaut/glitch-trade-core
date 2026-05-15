"""
End-to-end smoke test for the IR → bar_replay adapter.

No DB needed: we monkeypatch `load_bars` with a synthetic bar series
shaped to deliberately trigger each IR shape's signal pathway.

Run with: .venv/bin/python -m ir.test_runner
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# We import the runner module so we can monkeypatch the load_bars
# name it pulled in from backtest.bar_replay.bars.
import ir.runner as runner
from backtest.bar_replay.bars import BAR_DTYPE


def _synth_trend_bars(n: int = 1000) -> np.ndarray:
    """Synthetic EURUSD-ish bars with a clear uptrend + ATR (so the
    trend_follower sees crosses + ADX threshold + non-zero ATR)."""
    rng = np.random.default_rng(42)
    bars = np.zeros(n, dtype=BAR_DTYPE)

    # 1 bar/hour for ~42 days
    t0 = np.datetime64("2025-01-01T00:00:00", "s")
    bars["t"] = t0 + np.arange(n).astype("timedelta64[h]").astype("timedelta64[s]")

    # Trend up over time + sinusoidal swings + jitter so SMA9/EMA21
    # actually cross multiple times and ADX rises above 20 in stretches.
    trend = np.linspace(1.05, 1.15, n)
    swing = 0.005 * np.sin(np.linspace(0, 30, n))
    jitter = rng.normal(0, 0.0008, n).cumsum() * 0.05
    closes = trend + swing + jitter
    spread = 0.0005 + np.abs(rng.normal(0, 0.0003, n))
    bars["o"] = closes - rng.normal(0, 0.0003, n)
    bars["c"] = closes
    bars["h"] = np.maximum(bars["o"], bars["c"]) + spread
    bars["l"] = np.minimum(bars["o"], bars["c"]) - spread
    bars["v"] = 1000.0
    return bars


def _synth_quick_bars(entry: float, exit_: float, n: int = 200) -> np.ndarray:
    """Synthetic BTC-ish bars that touch `entry` then later touch `exit_`."""
    bars = np.zeros(n, dtype=BAR_DTYPE)
    t0 = np.datetime64("2025-01-01T00:00:00", "s")
    bars["t"] = t0 + np.arange(n).astype("timedelta64[h]").astype("timedelta64[s]")

    closes = np.full(n, 79_500.0)
    closes[40:80]  = np.linspace(79_500, 80_500, 40)   # cross entry @ 80000
    closes[80:140] = np.linspace(80_500, 81_500, 60)   # cross exit  @ 81000
    closes[140:]   = np.linspace(81_500, 80_000, n - 140)
    bars["o"] = closes
    bars["c"] = closes
    bars["h"] = closes + 50
    bars["l"] = closes - 50
    bars["v"] = 1.0
    return bars


def _patch(bars):
    """Patch load_bars at every call site (runner uses one path, sim.py
    imports its own reference via `from .bars import load_bars`)."""
    fake = lambda req: bars
    runner.load_bars = fake                            # type: ignore[attr-defined]
    import backtest.bar_replay.sim as _sim
    _sim.load_bars = fake                              # type: ignore[attr-defined]


def main() -> int:
    samples_dir = Path(__file__).parent / "samples"

    # ── Trend shape ───────────────────────────────────────────────────
    ir_trend = json.loads((samples_dir / "eurusd_trend_ftmo.json").read_text())
    _patch(_synth_trend_bars(1000))
    print(f"\n=== trend-shape IR: {ir_trend['name']} ===")
    res = runner.run_ir(ir_trend, ruleset="ftmo", starting_balance=25_000)
    assert res["config"]["shape"] == "trend-follower", res["config"]
    print(f"  shape         : {res['config']['shape']}")
    print(f"  passes        : {res['passes']}  alive={res['alive']}  terminated={res['terminated']}")
    print(f"  trades        : {res['trades']}")
    print(f"  total_pnl_pct : {res['total_pnl_pct']:.4f}")
    print(f"  max_day_loss  : {res['max_day_loss_pct']:.4f}")

    # ── Quick shape ───────────────────────────────────────────────────
    ir_quick = json.loads((samples_dir / "quick_btc_80_to_81.json").read_text())
    _patch(_synth_quick_bars(entry=80_000, exit_=81_000, n=200))
    print(f"\n=== quick-shape IR: {ir_quick['name']} ===")
    res = runner.run_ir(ir_quick, ruleset="fundingpips_zero", starting_balance=25_000)
    assert res["config"]["shape"] == "quick-rule", res["config"]
    assert res["trades"] >= 1, f"expected ≥1 trade, got {res['trades']}"
    print(f"  shape         : {res['config']['shape']}")
    print(f"  trades        : {res['trades']}")
    print(f"  total_pnl_pct : {res['total_pnl_pct']:.4f}")
    print(f"  ending_balance: {res['ending_balance']:.2f}")

    # ── Quick parser → IR → runner round-trip ─────────────────────────
    from ir.quick_parse import to_ir
    ir_parsed = to_ir("buy BTCUSD at 80000, sell at 81000 with 0.05 units")
    _patch(_synth_quick_bars(entry=80_000, exit_=81_000, n=200))
    print(f"\n=== parser → IR → runner round-trip ===")
    res = runner.run_ir(ir_parsed, ruleset="fundingpips_zero", starting_balance=25_000)
    assert res["trades"] >= 1, "round-trip expected ≥1 trade"
    print(f"  trades        : {res['trades']}")
    print(f"  total_pnl_pct : {res['total_pnl_pct']:.4f}")

    # ── Unsupported shape rejected cleanly ────────────────────────────
    print(f"\n=== unsupported shape raises UnsupportedIRShape ===")
    weird = {
        "name": "weird", "version": 1,
        "instruments": [{"symbol": "EURUSD", "timeframe": "h1"}],
        "indicators": [{"id": "rsi", "type": "rsi", "period": 14}],
        "entries": [{"side": "long", "when": "rsi < 30"}],
        "exits":   [{"type": "take_profit", "at_r": 1.0}],
    }
    try:
        runner.run_ir(weird, ruleset="ftmo")
    except runner.UnsupportedIRShape as e:
        print(f"  ok — raised: {str(e)[:80]}…")
    else:
        print("  FAIL — should have raised")
        return 1

    print("\n✅ all IR adapter smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
