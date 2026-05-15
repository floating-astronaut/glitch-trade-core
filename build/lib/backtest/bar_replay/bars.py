"""
Historical bar loader.

Pulls m1 OHLCV from `ml_bars` for a (symbol, window) pair and aggregates
up to any minute-multiple timeframe (m5, m15, m30, h1, h4) so the
strategy can run on whatever bar size matches its design (trend_follower
was designed for h1 — not natively present in ml_bars, so we aggregate
m1 → h1 here).

Output is a numpy structured array shape (N,) with columns
[t (UTC datetime64), o, h, l, c, v]. Strategy + indicator code consume
this shape directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

BAR_DTYPE = np.dtype([
    ("t", "datetime64[s]"),
    ("o", "f8"),
    ("h", "f8"),
    ("l", "f8"),
    ("c", "f8"),
    ("v", "f8"),
])


def _ml_dsn() -> str:
    return os.environ.get(
        "ML_DATABASE_URL",
        "postgresql://glitchml_ro@/glitch_ml?host=/var/run/postgresql",
    )


def _connect():
    return psycopg2.connect(_ml_dsn(), cursor_factory=RealDictCursor)


@dataclass(frozen=True)
class BarsRequest:
    symbol: str
    timeframe: str           # 'm1' | 'm5' | 'm15' | 'm30' | 'h1' | 'h4'
    start: Optional[datetime] = None
    end: Optional[datetime] = None


_TF_MINUTES = {
    "m1": 1, "m5": 5, "m15": 15, "m30": 30, "h1": 60, "h4": 240,
}


def load_bars(req: BarsRequest) -> np.ndarray:
    """Load bars at the requested timeframe. Aggregates from m1 if the
    requested timeframe doesn't exist natively in ml_bars."""
    tf = req.timeframe.lower()
    if tf not in _TF_MINUTES:
        raise ValueError(f"unknown timeframe {tf!r}; supported: {list(_TF_MINUTES)}")
    minutes = _TF_MINUTES[tf]

    # Try the native timeframe first; if no rows, fall back to m1 + aggregate.
    native = _query_native(req.symbol, tf, req.start, req.end)
    if native.size > 0:
        return native

    if tf == "m1":
        return native
    m1 = _query_native(req.symbol, "m1", req.start, req.end)
    return _aggregate_minutes(m1, minutes) if m1.size > 0 else m1


def _query_native(symbol: str, tf: str, start, end) -> np.ndarray:
    where = ["symbol = %s", "timeframe = %s"]
    params: list = [symbol, tf]
    if start is not None:
        where.append("bar_time >= %s")
        params.append(start)
    if end is not None:
        where.append("bar_time < %s")
        params.append(end)
    sql = f"""
        SELECT bar_time, open, high, low, close, volume
        FROM ml_bars
        WHERE {' AND '.join(where)}
        ORDER BY bar_time ASC
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return np.empty((0,), dtype=BAR_DTYPE)
    out = np.empty(len(rows), dtype=BAR_DTYPE)
    for i, r in enumerate(rows):
        out[i] = (
            np.datetime64(r["bar_time"].astimezone(timezone.utc).replace(tzinfo=None), "s"),
            float(r["open"] or 0),
            float(r["high"] or 0),
            float(r["low"] or 0),
            float(r["close"] or 0),
            float(r["volume"] or 0),
        )
    return out


def _aggregate_minutes(m1: np.ndarray, n_minutes: int) -> np.ndarray:
    """Aggregate m1 bars into n-minute buckets aligned on UTC boundaries.
    Skips buckets with no underlying bars (no synthetic fills)."""
    if m1.size == 0:
        return m1
    # Bucket key in minutes-since-epoch, floored to the n_minutes boundary.
    epoch = m1["t"].astype("int64")  # seconds
    bucket = (epoch // (n_minutes * 60)) * (n_minutes * 60)
    # Group consecutive equal buckets.
    boundaries = np.concatenate(([0], np.where(bucket[1:] != bucket[:-1])[0] + 1, [m1.size]))
    n_groups = len(boundaries) - 1
    out = np.empty(n_groups, dtype=BAR_DTYPE)
    for i in range(n_groups):
        a, b = boundaries[i], boundaries[i + 1]
        seg = m1[a:b]
        out[i] = (
            np.datetime64(int(bucket[a]), "s"),
            seg["o"][0],
            seg["h"].max(),
            seg["l"].min(),
            seg["c"][-1],
            seg["v"].sum(),
        )
    return out
