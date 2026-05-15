"""
Strategy port — trend_follower in pure Python.

Mirrors `glitch-trade-core/ctrader-store/trend-follower/GlitchTrendFollower.cs`
math-for-math so HPO results map 1:1 onto the cAlgo cBot the customer
runs. If you change one, change the other.

Returns one signal per closed bar:

    Signal {
        idx:        bar index
        vote:       +1 (BUY) | -1 (SELL) | 0 (HOLD)
        confidence: 0.0–0.90
        atr:        current ATR (used by the position manager for SL/TP)
    }
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .indicators import sma, ema, adx, atr, rolling_median


@dataclass(frozen=True)
class TrendFollowerParams:
    sma_period: int = 9
    ema_period: int = 21
    adx_period: int = 14
    atr_period: int = 14
    crossover_lookback: int = 5
    atr_median_window: int = 100

    adx_min_trend: float = 15.0
    adx_strong: float = 25.0
    adx_mid: float = 20.0

    strong_confidence: float = 0.90
    mid_confidence: float = 0.75
    low_confidence: float = 0.60
    low_vol_penalty: float = 0.15
    min_confidence_floor: float = 0.45


@dataclass
class Signal:
    idx: int
    vote: int        # +1 | 0 | -1
    confidence: float
    atr: float


def run_trend_follower(bars: np.ndarray, p: TrendFollowerParams) -> list[Signal]:
    """Run trend_follower over an OHLC bars array; return one Signal per bar."""
    if bars.size == 0:
        return []

    h = bars["h"].astype("f8")
    l = bars["l"].astype("f8")
    c = bars["c"].astype("f8")

    sma_v = sma(c, p.sma_period)
    ema_v = ema(c, p.ema_period)
    adx_v = adx(h, l, c, p.adx_period)
    atr_v = atr(h, l, c, p.atr_period)
    atr_med = rolling_median(atr_v, p.atr_median_window)

    min_bars = max(p.ema_period + p.crossover_lookback,
                   max(p.adx_period, p.atr_period) + 2)

    out: list[Signal] = []
    for i in range(bars.size):
        if i < min_bars:
            out.append(Signal(idx=i, vote=0, confidence=0.0, atr=0.0))
            continue
        sma_now = sma_v[i]
        ema_now = ema_v[i]
        adx_now = adx_v[i]
        atr_now = atr_v[i]
        if any(np.isnan(x) for x in (sma_now, ema_now, adx_now, atr_now)):
            out.append(Signal(idx=i, vote=0, confidence=0.0, atr=0.0))
            continue

        # Crossover detection in the last N bars (matches the cAlgo loop)
        bullish = bearish = False
        first = max(1, i - p.crossover_lookback + 1)
        for k in range(first, i + 1):
            sp, ep = sma_v[k - 1], ema_v[k - 1]
            sn, en = sma_v[k],     ema_v[k]
            if any(np.isnan(x) for x in (sp, ep, sn, en)):
                continue
            if sp <= ep and sn > en: bullish = True
            elif sp >= ep and sn < en: bearish = True

        if adx_now <= p.adx_min_trend or (not bullish and not bearish):
            out.append(Signal(idx=i, vote=0, confidence=0.0, atr=float(atr_now)))
            continue

        if   adx_now >= p.adx_strong: conf = p.strong_confidence
        elif adx_now >= p.adx_mid:    conf = p.mid_confidence
        else:                         conf = p.low_confidence

        med = atr_med[i]
        if not np.isnan(med) and atr_now < med:
            conf = max(p.min_confidence_floor, conf - p.low_vol_penalty)

        out.append(Signal(idx=i, vote=1 if bullish else -1,
                          confidence=round(conf, 2), atr=float(atr_now)))
    return out
