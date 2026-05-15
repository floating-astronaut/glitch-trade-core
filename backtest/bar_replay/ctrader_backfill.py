"""
Historical bar backfill from cTrader Open API into Postgres `ml_bars`.

Uses the existing `CTraderPriceFeed` (lives in /opt/glitch-ouroboros/ctrader/
ensemble/ctrader_price_feed.py) for the protobuf wiring — we don't want to
re-implement the auth + framing dance. We subclass it to add an explicit
time-range fetcher and a backward-paginating loop.

Why this matters
----------------
The 30-day window in ml_bars is too thin for HPO to distinguish edge from
noise (see `walk_forward.py` cold-bath result: every winner was overfit).
Backfilling 2-5 years of H1 bars gives the simulator real statistical
power.

cTrader Open API caps a single trendbars request at ~5000 bars per call,
so we page backward in fixed-bar windows until we hit the start date or
the broker stops returning data.

Run
---
The cTrader Open API credentials live in
`/opt/glitch-ouroboros/ctrader/ml_collector/.env`. Source that env and run:

    set -a; . /opt/glitch-ouroboros/ctrader/ml_collector/.env; set +a
    python -m backtest.bar_replay.ctrader_backfill \\
        --symbols JPN225,EURUSD,BTCUSD,GER40,XAUUSD,UK100 \\
        --timeframe h1 \\
        --years 3

Run from a host with python access to the glitch_ml DB (the simulator
container has it; or use the ml_collector venv which has all the
protobuf deps already).

Idempotent: UPSERTs on (symbol, timeframe, bar_time). Re-running the
backfill on a populated DB is safe and fast (existing bars no-op).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ── Env loader (defensive) ──────────────────────────────────────────────────
# A previous run had this script inherit an empty env even though the user
# `set -a; . .env; set +a`'d the file — sudo -u under some configurations
# strips inheritance. Belt-and-suspenders: if CTRADER_* aren't already in
# os.environ, attempt to load from the standard ml_collector .env path
# directly via python-dotenv (already in the collector's venv).
def _ensure_ctrader_env() -> None:
    if all(os.environ.get(k) for k in (
        "CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET",
        "CTRADER_ACCESS_TOKEN", "CTRADER_ACCOUNT_ID",
    )):
        return
    candidates = [
        Path(os.environ.get("CTRADER_ENV_FILE", "")),
        Path("/opt/glitch-ouroboros/ctrader/ml_collector/.env"),
        Path("/opt/glitch-ouroboros/ctrader/.env"),
    ]
    for p in candidates:
        if p and p.is_file():
            try:
                from dotenv import load_dotenv
                load_dotenv(p, override=False)
                logging.info("loaded env from %s", p)
                return
            except Exception as e:
                logging.warning("dotenv load failed for %s: %s", p, e)


_ensure_ctrader_env()

# The CTraderPriceFeed source isn't installed as a package; bring it in
# from /opt explicitly. Order matters — must precede the import.
_OPT = "/opt/glitch-ouroboros/ctrader"
if _OPT not in sys.path:
    sys.path.insert(0, _OPT)
sys.path.insert(0, os.path.join(_OPT, "ml_collector"))  # for _ctrader_compat
try:
    from ml_collector import _ctrader_compat  # noqa: F401  must come first
except Exception:
    pass
from ensemble.ctrader_price_feed import (  # type: ignore
    CTraderPriceFeed, _TF_MAP, PT_TRENDBARS_REQ, PT_TRENDBARS_RES,
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import (  # type: ignore
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
)

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger("ctrader_backfill")

# Conservative ceilings. cTrader returns at most ~5000 trendbars/req for h1
# (lower for finer timeframes). Page in 4000-bar chunks to leave headroom.
_BARS_PER_PAGE = 4000

# Minute-multiples per timeframe — used to compute the request window in ms.
_TF_MINUTES = {"m1": 1, "m5": 5, "m15": 15, "m30": 30, "h1": 60, "h4": 240}


class HistoricalFeed(CTraderPriceFeed):
    """CTraderPriceFeed extended with explicit time-range fetches."""

    async def _fetch_bars_range(
        self, reader, writer, symbol_id: int, digits: int,
        tf_enum: int, from_ms: int, to_ms: int, count: int,
    ) -> Optional[np.ndarray]:
        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = self.account_id
        req.symbolId = symbol_id
        req.period = tf_enum
        req.fromTimestamp = from_ms
        req.toTimestamp = to_ms
        req.count = count
        mid = str(uuid.uuid4())[:8]
        writer.write(self._frame(PT_TRENDBARS_REQ, req.SerializeToString(), mid))
        await writer.drain()
        res_msg = await self._recv_until(reader, [PT_TRENDBARS_RES], mid, timeout=30)
        res = ProtoOAGetTrendbarsRes()
        res.ParseFromString(res_msg.payload)
        if not res.trendbar:
            return None
        divisor = 10.0 ** digits
        rows = []
        for bar in res.trendbar:
            ts = bar.utcTimestampInMinutes * 60
            low = bar.low / divisor
            rows.append([
                ts,
                (bar.low + bar.deltaOpen) / divisor,
                (bar.low + bar.deltaHigh) / divisor,
                low,
                (bar.low + bar.deltaClose) / divisor,
                float(bar.volume) if bar.HasField("volume") else 0.0,
            ])
        if not rows:
            return None
        arr = np.array(rows, dtype=float)
        return arr[arr[:, 0].argsort()]

    def fetch_history(
        self, symbol: str, timeframe: str, from_dt: datetime, to_dt: datetime,
    ) -> np.ndarray:
        """Page backward from `to_dt` to `from_dt`, return one numpy array
        sorted ascending by ts (column 0)."""
        tf = timeframe.lower()
        tf_enum = _TF_MAP.get(tf)
        if tf_enum is None:
            raise ValueError(f"unsupported timeframe {tf!r} (have {list(_TF_MAP)})")
        sym_info = self._get_symbol_info(symbol)
        if not sym_info:
            raise SystemExit(f"symbol {symbol!r} not on broker account")
        symbol_id, digits = sym_info
        period_ms = _TF_MINUTES[tf] * 60 * 1000
        from_ms = int(from_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = int(to_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

        all_rows: list[np.ndarray] = []
        cursor_to = end_ms
        while cursor_to > from_ms:
            window_from = max(from_ms, cursor_to - _BARS_PER_PAGE * period_ms)

            async def page(r, w):
                return await self._fetch_bars_range(
                    r, w, symbol_id, digits, tf_enum,
                    window_from, cursor_to, _BARS_PER_PAGE,
                )
            try:
                arr = asyncio.run(self._session(page))
            except Exception as e:
                logger.error("page fetch failed: %s", e)
                break
            if arr is None or arr.size == 0:
                logger.info("  %s %s: broker returned no bars at %s — stopping",
                            symbol, tf, datetime.fromtimestamp(window_from / 1000, tz=timezone.utc))
                break
            all_rows.append(arr)
            oldest = arr[0, 0]  # earliest ts in this page (seconds)
            logger.info("  %s %s: %d bars, oldest %s",
                        symbol, tf, len(arr),
                        datetime.fromtimestamp(oldest, tz=timezone.utc).isoformat())
            # Step the cursor back to one period before the oldest bar we got.
            cursor_to = int(oldest * 1000) - period_ms
            time.sleep(0.4)  # polite to the broker

        if not all_rows:
            return np.empty((0, 6), dtype=float)
        merged = np.vstack(all_rows)
        # Dedupe + sort by ts
        _, uniq = np.unique(merged[:, 0], return_index=True)
        return merged[np.sort(uniq)]


# ── Postgres writer ──────────────────────────────────────────────────────────

def _ml_dsn() -> str:
    return os.environ.get(
        "ML_DATABASE_URL",
        "postgresql://glitchml_ro@/glitch_ml?host=/var/run/postgresql",
    )


def upsert_bars(symbol: str, timeframe: str, rows: np.ndarray) -> int:
    """UPSERT into ml_bars (symbol, timeframe, bar_time) → returns row count
    actually written. Idempotent by composite key."""
    if rows.size == 0:
        return 0
    payload = [
        (
            symbol,
            timeframe,
            datetime.fromtimestamp(int(r[0]), tz=timezone.utc),
            float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]),
        )
        for r in rows
    ]
    conn = psycopg2.connect(_ml_dsn())
    try:
        with conn.cursor() as cur:
            # Ensure a unique key the UPSERT can target. The base ml_bars table
            # has no UNIQUE constraint on (symbol, timeframe, bar_time) by
            # default; create it if missing (no-op on second run).
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_ml_bars_sym_tf_time
                ON ml_bars(symbol, timeframe, bar_time)
            """)
            execute_values(cur, """
                INSERT INTO ml_bars (symbol, timeframe, bar_time, open, high, low, close, volume)
                VALUES %s
                ON CONFLICT (symbol, timeframe, bar_time) DO NOTHING
            """, payload, page_size=1000)
            conn.commit()
    finally:
        conn.close()
    return len(payload)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="backtest.bar_replay.ctrader_backfill")
    p.add_argument("--symbols",   required=True,
                   help="Comma-separated symbol list, e.g. JPN225,EURUSD,BTCUSD")
    p.add_argument("--timeframe", default="h1")
    p.add_argument("--years",     type=int, default=3)
    p.add_argument("--end",       help="ISO end date (default now)")
    p.add_argument("--verbose",   action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Fail fast with a useful message if env still isn't populated after the
    # _ensure_ctrader_env() loader at module import time. Saves the user from
    # the silent "Symbol cache refresh failed: CH_CLIENT_AUTH_FAILURE" path.
    missing = [k for k in (
        "CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET",
        "CTRADER_ACCESS_TOKEN", "CTRADER_ACCOUNT_ID",
    ) if not os.environ.get(k)]
    if missing:
        print(
            f"\nERROR: cTrader credentials not in env: {', '.join(missing)}\n"
            f"Try one of:\n"
            f"  1. Set CTRADER_ENV_FILE=/path/to/.env and re-run\n"
            f"  2. Run from /opt/glitch-ouroboros/ctrader/ml_collector/venv with cwd in that dir\n"
            f"  3. Export CTRADER_CLIENT_ID/SECRET/ACCESS_TOKEN/ACCOUNT_ID inline\n",
            file=sys.stderr,
        )
        return 2

    end_dt = datetime.fromisoformat(args.end) if args.end else datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=365 * args.years)

    feed = HistoricalFeed()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print(f"\n=== cTrader backfill ===")
    print(f"  range:     {start_dt.date()} → {end_dt.date()}  ({args.years} yr)")
    print(f"  timeframe: {args.timeframe}")
    print(f"  symbols:   {', '.join(symbols)}\n")

    for sym in symbols:
        t0 = time.time()
        try:
            rows = feed.fetch_history(sym, args.timeframe, start_dt, end_dt)
        except Exception as e:
            print(f"  {sym}: ✗ fetch failed: {e}")
            continue
        wrote = upsert_bars(sym, args.timeframe, rows)
        dt = time.time() - t0
        print(f"  {sym}: ✓ {wrote:>6} bars in {dt:.1f}s "
              f"(span: {datetime.fromtimestamp(rows[0,0], tz=timezone.utc).date() if rows.size else '—'} "
              f"→ {datetime.fromtimestamp(rows[-1,0], tz=timezone.utc).date() if rows.size else '—'})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
