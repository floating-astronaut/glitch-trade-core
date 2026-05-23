"""
Single-config simulator.

Wraps:    bars → trend_follower signals → position manager → FundingPips Zero rules → result

Result is a dict — easy to JSONify, easy to compare across thousands of
configs, easy to feed into Optuna's `optimize(...)` objective.

The fitness function (sweep.py / objective) is a simple composition:
   passes  > anything
   then by total PnL %
   then by lower max DD %
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np

from ..account import VirtualAccount
from ..rules import FUNDINGPIPS_ZERO, Rules
from ..sizer import POINT_VALUE_USD_PER_LOT
from .bars import BarsRequest, load_bars
from .strategy import TrendFollowerParams, run_trend_follower
from .manager import ManagerParams, manage_trade


@dataclass(frozen=True)
class SimConfig:
    symbol: str
    timeframe: str = "h1"
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    starting_balance: float = 25_000
    rules: Rules = FUNDINGPIPS_ZERO
    strategy: TrendFollowerParams = TrendFollowerParams()
    manager: ManagerParams = ManagerParams()


def run_sim(cfg: SimConfig) -> dict:
    bars = load_bars(BarsRequest(cfg.symbol, cfg.timeframe, cfg.start, cfg.end))
    if bars.size < 100:
        return _empty_result(cfg, reason=f"insufficient bars ({bars.size})")

    signals = run_trend_follower(bars, cfg.strategy)

    point_value = POINT_VALUE_USD_PER_LOT.get(cfg.symbol, 100_000.0)
    start_ts = bars["t"][0].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
    acc = VirtualAccount(cfg.starting_balance, cfg.rules, start_ts=start_ts)

    trades_done = 0
    trades_capped = 0

    # Walk signals in order; the manager opens at sig.idx + 1, so we can't
    # take overlapping signals — skip any signal whose open_idx is before
    # the previous trade's close.
    next_avail_idx = 0
    for sig in signals:
        if acc.terminated:           break
        if sig.idx < next_avail_idx: continue
        # Soft halt + termination check before paper-opening
        ts = bars[sig.idx]["t"].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
        if acc.before_open(ts) is not None: continue

        result = manage_trade(bars, sig, cfg.manager)
        if result is None: continue
        next_avail_idx = result.close_idx + 1

        # Convert PRICE-units PnL → $-PnL using a position size that targets
        # `target_risk` at the trade's SL distance.
        # Use current balance so profitable strategies compound position size.
        sl_distance = abs(result.entry - result.sl_at_entry)
        if sl_distance <= 0: continue
        target_risk = acc.balance * cfg.rules.risk_per_trade_pct
        # lots required to make sl_distance × point_value × lots == target_risk
        lots = target_risk / (sl_distance * point_value)
        # Hard cap so a freak SL doesn't trigger the position-sizer to size up
        # arbitrarily — never risk more than the rules' hard cap.
        max_lots = (acc.balance * cfg.rules.risk_per_trade_pct_hard_cap) \
                   / (sl_distance * point_value)
        if lots > max_lots:
            lots = max_lots
            trades_capped += 1
        usd_pnl = result.pnl_per_lot * point_value * lots

        close_ts = bars[result.close_idx]["t"].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
        acc.record_close(close_ts, usd_pnl)
        trades_done += 1

    # Final day rollup
    if not acc.terminated and bars.size:
        last_ts = bars["t"][-1].astype("M8[s]").astype("O").replace(tzinfo=timezone.utc)
        acc.roll_day(last_ts)

    summary = acc.summary()

    # Drawdown summary across the full equity timeline isn't tracked
    # tick-by-tick; approximate by max-day-loss / pct-from-HWM at end.
    max_day_loss_pct = (
        min((d.realised_pnl for d in acc.daily_records), default=0.0)
        / cfg.starting_balance
    )
    pct_from_hwm = (acc.balance - acc.equity_hwm) / acc.equity_hwm if acc.equity_hwm else 0.0

    return {
        "passes":          not summary["terminated"]
                            and summary["total_pnl_pct"] >= cfg.rules.min_withdraw_total_pct,
        "alive":           not summary["terminated"],
        "terminated":      summary["terminated"],
        "breach":          summary.get("breach"),
        "total_pnl_pct":   summary["total_pnl_pct"],
        "max_day_loss_pct": max_day_loss_pct,
        "pct_from_hwm":    pct_from_hwm,
        "trades":          trades_done,
        "trades_capped":   trades_capped,
        "days_traded":     summary["days_traded"],
        "profitable_days": summary["profitable_days"],
        "ending_balance":  summary["ending_balance"],
        "hwm":             summary["equity_hwm"],
        "config": {
            "symbol": cfg.symbol,
            "timeframe": cfg.timeframe,
            "starting_balance": cfg.starting_balance,
            "strategy": asdict(cfg.strategy),
            "manager":  asdict(cfg.manager),
        },
    }


def _empty_result(cfg: SimConfig, reason: str) -> dict:
    return {
        "passes": False,
        "alive": False,
        "terminated": False,
        "breach": None,
        "total_pnl_pct": 0.0,
        "max_day_loss_pct": 0.0,
        "pct_from_hwm": 0.0,
        "trades": 0,
        "trades_capped": 0,
        "days_traded": 0,
        "profitable_days": 0,
        "ending_balance": cfg.starting_balance,
        "hwm": cfg.starting_balance,
        "skipped_reason": reason,
        "config": {"symbol": cfg.symbol, "timeframe": cfg.timeframe},
    }
