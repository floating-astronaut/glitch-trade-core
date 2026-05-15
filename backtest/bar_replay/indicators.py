"""
Pure-Python OHLC indicators. Mirror the cAlgo math we use in the
GlitchTrendFollower indicator/cBot so simulator results map 1:1 onto
what buyers see when they backtest the cBot in cTrader Desktop.

Numpy-only. No talib, no pandas. Each function returns a same-length
array with NaN where there isn't enough history.
"""
from __future__ import annotations

import numpy as np


def sma(x: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    out = np.full_like(x, np.nan, dtype="f8")
    if period < 1 or x.size < period:
        return out
    cs = np.cumsum(np.insert(x.astype("f8"), 0, 0.0))
    out[period - 1:] = (cs[period:] - cs[:-period]) / period
    return out


def ema(x: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average — same recurrence cAlgo uses."""
    out = np.full_like(x, np.nan, dtype="f8")
    if period < 1 or x.size < period:
        return out
    alpha = 2.0 / (period + 1.0)
    # Seed with SMA(period) so the EMA series matches cAlgo's, not pandas'.
    seed = float(np.mean(x[:period]))
    out[period - 1] = seed
    prev = seed
    for i in range(period, x.size):
        prev = alpha * x[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Wilder's true range. tr[0] = h[0]-l[0]; thereafter max of three."""
    n = h.size
    tr = np.empty(n, dtype="f8")
    if n == 0:
        return tr
    tr[0] = h[0] - l[0]
    if n > 1:
        a = h[1:] - l[1:]
        b = np.abs(h[1:] - c[:-1])
        d = np.abs(l[1:] - c[:-1])
        tr[1:] = np.maximum(a, np.maximum(b, d))
    return tr


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    """ATR via simple moving average of true range. Matches cAlgo's
    AverageTrueRange(period, MovingAverageType.Simple)."""
    return sma(true_range(h, l, c), period)


def adx(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's Average Directional Index. Mirrors the ADX series of
    cAlgo's DirectionalMovementSystem."""
    n = h.size
    out = np.full(n, np.nan, dtype="f8")
    if n < period + 1:
        return out

    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(h, l, c)[1:]  # length n-1, aligned with plus/minus_dm

    # Wilder smoothing (alpha = 1/period) with SMA seed.
    def _wilder(x):
        s = np.full(x.size, np.nan, dtype="f8")
        if x.size < period:
            return s
        s[period - 1] = x[:period].sum()
        for i in range(period, x.size):
            s[i] = s[i - 1] - s[i - 1] / period + x[i]
        return s

    sm_tr   = _wilder(tr)
    sm_plus = _wilder(plus_dm)
    sm_minus= _wilder(minus_dm)

    with np.errstate(invalid="ignore", divide="ignore"):
        plus_di  = 100.0 * sm_plus  / sm_tr
        minus_di = 100.0 * sm_minus / sm_tr
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)

    # ADX is a Wilder smoothing of DX itself, then aligned back to length n.
    valid = ~np.isnan(dx)
    if valid.sum() < period:
        return out
    adx_inner = np.full(dx.size, np.nan, dtype="f8")
    first = np.where(valid)[0][0]
    adx_inner[first + period - 1] = np.nanmean(dx[first:first + period])
    for i in range(first + period, dx.size):
        prev = adx_inner[i - 1]
        if np.isnan(prev):
            continue
        adx_inner[i] = (prev * (period - 1) + dx[i]) / period

    # Shift +1 to align with bar index (dx was computed on bars 1..n-1).
    out[1:] = adx_inner
    return out


def rolling_median(x: np.ndarray, window: int) -> np.ndarray:
    """Rolling median, NaN-safe. Slow O(n*w) but adequate for our N."""
    out = np.full_like(x, np.nan, dtype="f8")
    n = x.size
    for i in range(n):
        a = max(0, i - window + 1)
        seg = x[a:i + 1]
        seg = seg[~np.isnan(seg)]
        if seg.size:
            out[i] = float(np.median(seg))
    return out
