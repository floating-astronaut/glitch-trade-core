"""
IR → bar_replay adapter.

Lets the existing simulator (`backtest.bar_replay.run_sim`) accept an
IR dict directly, so a strategy authored in the visual builder /
quick-rule textarea / code editor can be backtested without going
through the IR → cAlgo C# compiler in the loop.

v1 covers the two IR shapes that match our seed templates:

  1. **Trend-follower shape** — indicators include sma+ema+adx+atr,
     entries use `crosses_above` / `crosses_below`, exits include
     stop_loss + partial_tp + trailing. Dispatches to the existing
     `run_trend_follower` + `manage_trade` path with parameters
     extracted from the IR.

  2. **Quick-rule shape** — no indicators, single entry with
     `price >=` / `price <=`, single `limit` exit. Dispatches to a
     simple price-trigger signal generator (in this module).

Anything else raises `UnsupportedIRShape`. Weeks 3–4 build the
general IR interpreter that handles arbitrary blocks; for now this
adapter exists to PROVE the IR is expressive enough for the engine
to run our two canonical seed strategies end-to-end.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import numpy as np

from backtest.bar_replay.bars import BarsRequest, load_bars
from backtest.bar_replay.manager import ManagerParams, manage_trade
from backtest.bar_replay.sim import SimConfig, run_sim, _empty_result
from backtest.bar_replay.strategy import Signal, TrendFollowerParams
from backtest.account import VirtualAccount
from backtest.rules import RULESETS, Rules, FUNDINGPIPS_ZERO
from backtest.sizer import POINT_VALUE_USD_PER_LOT
from datetime import timezone

from . import validate


class UnsupportedIRShape(NotImplementedError):
    """Raised when an IR doesn't match a shape this v1 adapter handles."""


# ── Shape detection ────────────────────────────────────────────────────

def _is_trend_shape(ir: dict[str, Any]) -> bool:
    inds = {i.get("type") for i in ir.get("indicators", [])}
    if not ({"sma", "ema", "adx", "atr"} <= inds):
        return False
    entry_whens = " ".join(e.get("when", "") for e in ir["entries"]).lower()
    return "crosses_above" in entry_whens or "crosses_below" in entry_whens


def _is_quick_shape(ir: dict[str, Any]) -> bool:
    if ir.get("indicators"):
        return False
    if len(ir["entries"]) != 1 or len(ir["exits"]) != 1:
        return False
    if ir["exits"][0].get("type") != "limit":
        return False
    when = ir["entries"][0].get("when", "")
    return bool(re.match(r"^\s*price\s*[<>]=?", when))


# ── Trend-shape adapter ────────────────────────────────────────────────

_NUM = r"-?\d+(?:\.\d+)?"


def _ir_to_trend_params(ir: dict[str, Any]) -> tuple[TrendFollowerParams, ManagerParams]:
    """Extract TrendFollowerParams + ManagerParams from a trend-shape IR."""
    inds = {i["type"]: i for i in ir["indicators"]}

    # ADX threshold from "adx > 20" in the entry expression
    entry_when = ir["entries"][0]["when"]
    m = re.search(rf"adx\s*>\s*({_NUM})", entry_when)
    adx_min = float(m.group(1)) if m else 15.0

    strat = TrendFollowerParams(
        sma_period=inds["sma"].get("period", 9),
        ema_period=inds["ema"].get("period", 21),
        adx_period=inds["adx"].get("period", 14),
        atr_period=inds["atr"].get("period", 14),
        adx_min_trend=adx_min,
    )

    sl_atr_mult = 1.5
    tp1_r = 1.0
    tp1_fraction = 0.5
    trail_step_r = 0.5
    for ex in ir["exits"]:
        t = ex.get("type")
        if t == "stop_loss":
            sl_atr_mult = ex.get("spec", {}).get("atr_mult", sl_atr_mult)
        elif t == "partial_tp":
            tp1_r = ex.get("at_r", tp1_r)
            tp1_fraction = ex.get("fraction", tp1_fraction)
        elif t == "trailing":
            trail_step_r = ex.get("step_r", trail_step_r)

    mgr = ManagerParams(
        sl_atr_mult=sl_atr_mult,
        tp1_r=tp1_r,
        tp1_fraction=tp1_fraction,
        trail_step_r=trail_step_r,
        min_confidence=0.60,
    )
    return strat, mgr


# ── Quick-shape adapter ────────────────────────────────────────────────

@dataclass
class _QuickRule:
    side: str            # "long" | "short"
    entry_price: float
    exit_price: float
    fixed_units: float


def _parse_price_when(when: str) -> tuple[str, float]:
    m = re.match(rf"\s*price\s*(>=|<=|>|<)\s*({_NUM})\s*$", when)
    if not m:
        raise UnsupportedIRShape(f"can't parse price expression: {when!r}")
    return m.group(1), float(m.group(2))


def _ir_to_quick_rule(ir: dict[str, Any]) -> _QuickRule:
    entry = ir["entries"][0]
    exit_ = ir["exits"][0]
    entry_op, entry_price = _parse_price_when(entry["when"])
    exit_op,  exit_price  = _parse_price_when(exit_["when"])

    side = entry["side"]
    if side == "long" and entry_op not in (">=", ">"):
        raise UnsupportedIRShape("long quick-rule expects price >= ENTRY")
    if side == "short" and entry_op not in ("<=", "<"):
        raise UnsupportedIRShape("short quick-rule expects price <= ENTRY")

    size = entry.get("size") or {}
    fixed_units = float(size.get("fixed_units", size.get("fixed_lots", 0.01)))
    return _QuickRule(side=side, entry_price=entry_price,
                      exit_price=exit_price, fixed_units=fixed_units)


def _run_quick_rule(ir: dict[str, Any], rules: Rules,
                    start: Optional[datetime], end: Optional[datetime],
                    starting_balance: float) -> dict:
    """Walk bars; trigger an entry on the first bar where the price-cross
    condition is true; close on the first subsequent bar where the exit
    condition is true. Repeat until end of bars (re-arms after each exit)."""
    rule = _ir_to_quick_rule(ir)
    inst = ir["instruments"][0]
    symbol = inst["symbol"]
    timeframe = inst.get("timeframe", "h1")
    if timeframe == "tick":
        # No tick data in v1 — fall back to m1 if we have it, else h1.
        timeframe = "h1"

    bars = load_bars(BarsRequest(symbol, timeframe, start, end))
    if bars.size < 2:
        return _empty_result(SimConfig(symbol=symbol, timeframe=timeframe,
                                       starting_balance=starting_balance,
                                       rules=rules),
                             reason=f"insufficient bars ({bars.size})")

    point_value = POINT_VALUE_USD_PER_LOT.get(symbol, 100_000.0)
    start_ts = bars["t"][0].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
    acc = VirtualAccount(starting_balance, rules, start_ts=start_ts)

    h = bars["h"].astype("f8")
    l = bars["l"].astype("f8")

    trades_done = 0
    in_position = False
    pending_positions = 0          # opened but never closed (capital frozen)
    pending_open_ts = None
    last_close_price = None         # for unrealised-PnL estimate at end
    for i in range(bars.size):
        if acc.terminated:
            break
        ts = bars[i]["t"].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
        if acc.before_open(ts) is not None:
            continue
        bar_high = h[i]
        bar_low  = l[i]
        last_close_price = float(bars[i]["c"])

        if not in_position:
            triggered = (rule.side == "long"  and bar_high >= rule.entry_price) or \
                        (rule.side == "short" and bar_low  <= rule.entry_price)
            if triggered:
                in_position = True
                pending_positions += 1
                pending_open_ts = ts
        else:
            hit_target = (rule.side == "long"  and bar_high >= rule.exit_price) or \
                         (rule.side == "short" and bar_low  <= rule.exit_price)
            if hit_target:
                price_pnl = (rule.exit_price - rule.entry_price) if rule.side == "long" \
                            else (rule.entry_price - rule.exit_price)
                usd_pnl = price_pnl * point_value * rule.fixed_units
                acc.record_close(ts, usd_pnl)
                trades_done += 1
                in_position = False
                pending_positions -= 1

    if not acc.terminated and bars.size:
        last_ts = bars["t"][-1].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
        acc.roll_day(last_ts)

    summary = acc.summary()
    max_day_loss_pct = (
        min((d.realised_pnl for d in acc.daily_records), default=0.0)
        / starting_balance
    )
    pct_from_hwm = (acc.balance - acc.equity_hwm) / acc.equity_hwm if acc.equity_hwm else 0.0

    # Unrealised PnL of any still-open position at end of bars. The quick-rule
    # has no SL, so a position opened at rule.entry_price sits there forever
    # waiting for rule.exit_price. We mark-to-market against the last close.
    unrealised_pnl = 0.0
    if pending_positions > 0 and last_close_price is not None:
        price_diff = (last_close_price - rule.entry_price) if rule.side == "long" \
                     else (rule.entry_price - last_close_price)
        unrealised_pnl = price_diff * point_value * rule.fixed_units

    # Honesty heuristics: warn the operator (and the SPA) when a backtest
    # looks artificially clean for known reasons.
    warnings: list[str] = []
    has_sl = any(ex.get("type") == "stop_loss" for ex in ir.get("exits", []))
    if not has_sl and pending_positions > 0:
        warnings.append(
            f"This rule has no stop-loss. {pending_positions} position(s) opened during the "
            f"backtest are still open at end of period — capital frozen until price returns to "
            f"the exit. Mark-to-market unrealised PnL: ${unrealised_pnl:,.2f}."
        )
    if not has_sl and trades_done > 0 and max_day_loss_pct == 0:
        warnings.append(
            "0% max day loss only because the rule has no stop-loss — losing positions are "
            "never closed, so they don't count against the daily-loss meter. Add a stop to "
            "stress-test honestly."
        )

    # Per-day series for the drawdown waterfall + per-day attribution on
    # /strategies/:id. Each entry mirrors backtest/account.DailyRecord
    # plus a running equity column so the SPA can chart equity-over-time
    # without recomputing on the client.
    running_eq = float(starting_balance)
    daily: list[dict] = []
    for d in acc.daily_records:
        running_eq = d.end_balance  # end_balance is the snapshot; pre-computed
        daily.append({
            "day": d.day,
            "start_balance": d.start_balance,
            "end_balance": d.end_balance,
            "realised_pnl": d.realised_pnl,
            "pnl_pct": d.pnl_pct,
            "n_trades": d.n_trades,
            "profitable": d.profitable,
            "equity": running_eq,
        })

    return {
        "passes": (not summary["terminated"]
                   and summary["total_pnl_pct"] >= rules.min_withdraw_total_pct),
        "alive": not summary["terminated"],
        "terminated": summary["terminated"],
        "breach": summary.get("breach"),
        "total_pnl_pct": summary["total_pnl_pct"],
        "max_day_loss_pct": max_day_loss_pct,
        "pct_from_hwm": pct_from_hwm,
        "trades": trades_done,
        "trades_capped": 0,
        "pending_positions": pending_positions,
        "unrealised_pnl": unrealised_pnl,
        "warnings": warnings,
        "days_traded": summary["days_traded"],
        "profitable_days": summary["profitable_days"],
        "ending_balance": summary["ending_balance"],
        "hwm": summary["equity_hwm"],
        # Per-day series (NEW): powers the drawdown waterfall + per-day
        # equity chart on /strategies/:id. Optional in the API contract
        # so cached older runs still deserialise cleanly.
        "daily": daily,
        "config": {"ir_name": ir["name"], "shape": "quick-rule",
                   "symbol": symbol, "timeframe": timeframe},
    }


# ── Public entry point ────────────────────────────────────────────────

def run_ir(ir: dict[str, Any], *,
           start: Optional[datetime] = None,
           end:   Optional[datetime] = None,
           starting_balance: float = 25_000,
           ruleset: Optional[str] = None) -> dict:
    """Validate IR, dispatch by shape, return the standard sim result dict."""
    validate(ir)

    firm = ruleset or (ir.get("guards") or {}).get("firm_rules") or "fundingpips_zero"
    if firm not in RULESETS:
        raise ValueError(f"unknown firm rule set: {firm!r}")
    rules = RULESETS[firm]

    inst = ir["instruments"][0]

    if _is_trend_shape(ir):
        strat, mgr = _ir_to_trend_params(ir)
        cfg = SimConfig(
            symbol=inst["symbol"], timeframe=inst.get("timeframe", "h1"),
            start=start, end=end,
            starting_balance=starting_balance, rules=rules,
            strategy=strat, manager=mgr,
        )
        result = run_sim(cfg)
        result["config"]["ir_name"]  = ir["name"]
        result["config"]["shape"]    = "trend-follower"
        # Unified shape so the SPA always sees the same fields.
        result.setdefault("pending_positions", 0)
        result.setdefault("unrealised_pnl", 0.0)
        result.setdefault("warnings", [])
        return result

    if _is_quick_shape(ir):
        return _run_quick_rule(ir, rules, start, end, starting_balance)

    raise UnsupportedIRShape(
        f"IR {ir['name']!r}: no matching shape adapter in v1. "
        "Trend-follower (sma+ema+adx+atr with crosses_above/below) and "
        "quick-rule (no indicators, single price-trigger entry, single "
        "limit exit) are the only shapes the v1 adapter handles. "
        "The general IR interpreter ships in week 3-4."
    )


# CLI
if __name__ == "__main__":
    import json, sys, argparse
    p = argparse.ArgumentParser(prog="ir.runner")
    p.add_argument("ir_path", help="path to IR JSON file")
    p.add_argument("--ruleset", default=None,
                   help="override IR's guards.firm_rules")
    p.add_argument("--balance", type=float, default=25_000)
    args = p.parse_args()

    with open(args.ir_path) as f:
        ir = json.load(f)
    result = run_ir(ir, starting_balance=args.balance, ruleset=args.ruleset)
    print(json.dumps(result, indent=2, default=str))
