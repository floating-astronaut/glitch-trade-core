"""Glitch Trade-API ingest adapter for MT5 bots.

Pushes account snapshots to https://trade-api.glitchexecutor.com/v1/
ingest/snapshot so the dashboard's Challenge page / alerts engine /
breach detector see live MT5 state.

This replaces the bots' old `dashboard.glitchexecutor.com/api/trades/
webhook` POST (the legacy admin-api endpoint), which only fired on
trade close. The new flow is a heartbeat — every N seconds the
ingestor reads `mt5.account_info()` + `mt5.positions_get()` and
POSTs the full snapshot. The server-side audit + idempotency layer
collapses duplicate posts; only the first per UTC-minute changes
state.

Drop-in usage in a bot:

    from shared.glitch_ingest import GlitchIngestor
    ingestor = GlitchIngestor.from_env(logger=logger)

    while not bot_stop.is_set():
        ingestor.maybe_tick()
        ...

`maybe_tick()` is throttled (30s default; tunable via env var) so
the call is cheap to make every strategy iteration.

ENVIRONMENT (all required for ingest to actually fire; missing ones
disable silently with one log line at startup so a misconfigured
bot doesn't crash — it just goes quiet on our dashboard):

  GLITCH_API_KEY        gtk_<prefix>.<secret> from /app/settings/api-keys
  GLITCH_INGEST_BASE    default https://trade-api.glitchexecutor.com
  GLITCH_MT5_LOGIN      MT5 account login (integer); matches the
                        accounts row's ctid_trader_account_id
  GLITCH_INGEST_INTERVAL_SECONDS  default 30

  GLITCH_FIRM_HINT             optional; auto-create anchor
  GLITCH_STARTING_BALANCE_HINT  optional
  GLITCH_TIER_HINT              optional

This module deliberately avoids any project dep — uses stdlib
`urllib.request` + `json` so a customer-side `pip install`
isn't needed beyond what the bot already brings.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

try:
    import MetaTrader5 as mt5  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — bots without MT5 import skip
    mt5 = None  # type: ignore[assignment]


class GlitchIngestor:
    """Throttled MT5-state → trade-api uploader.

    Construct via `GlitchIngestor.from_env(logger)`; call
    `maybe_tick()` from the bot's hot loop. Returns silently when
    disabled (missing env vars) or throttled.

    Failures (network, server reject) are logged at WARNING and
    counted but never raised. The bot must keep running even if
    the dashboard pipe is broken.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        login: int,
        interval_seconds: int,
        firm_hint: Optional[str] = None,
        starting_balance_hint: Optional[float] = None,
        tier_hint: Optional[str] = None,
        logger: Any = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._login = login
        self._interval = interval_seconds
        self._firm_hint = firm_hint
        self._starting_balance_hint = starting_balance_hint
        self._tier_hint = tier_hint
        self._log = logger
        self._last_tick_ts = 0.0
        self._consecutive_failures = 0

    # ── Constructor from env ─────────────────────────────────────────

    @classmethod
    def from_env(cls, *, logger: Any = None) -> Optional["GlitchIngestor"]:
        """Returns None when GLITCH_API_KEY or GLITCH_MT5_LOGIN are
        missing — the bot then runs without ingest, no crash. Logs
        one info line so the operator knows whether ingest is
        active."""
        api_key = os.environ.get("GLITCH_API_KEY", "").strip()
        login_raw = os.environ.get("GLITCH_MT5_LOGIN", "").strip()
        if not api_key or not login_raw:
            if logger:
                logger.info("glitch_ingest disabled (set GLITCH_API_KEY + GLITCH_MT5_LOGIN to enable)")
            return None
        try:
            login = int(login_raw)
        except ValueError:
            if logger:
                logger.warning("glitch_ingest disabled: GLITCH_MT5_LOGIN=%r is not an integer", login_raw)
            return None
        ingestor = cls(
            api_key=api_key,
            base_url=os.environ.get("GLITCH_INGEST_BASE", "https://trade-api.glitchexecutor.com"),
            login=login,
            interval_seconds=int(os.environ.get("GLITCH_INGEST_INTERVAL_SECONDS", "30")),
            firm_hint=os.environ.get("GLITCH_FIRM_HINT") or None,
            starting_balance_hint=(
                float(os.environ["GLITCH_STARTING_BALANCE_HINT"])
                if os.environ.get("GLITCH_STARTING_BALANCE_HINT") else None
            ),
            tier_hint=os.environ.get("GLITCH_TIER_HINT") or None,
            logger=logger,
        )
        if logger:
            logger.info("glitch_ingest enabled: login=%s interval=%ds → %s",
                        login, ingestor._interval, ingestor._base_url)
        return ingestor

    # ── Hot path ─────────────────────────────────────────────────────

    def maybe_tick(self) -> bool:
        """Throttled snapshot push. Call freely from a hot loop.

        Returns True iff a POST actually happened (accepted OR
        replayed by the server). Throttle-skip returns False
        silently."""
        now = time.time()
        if now - self._last_tick_ts < self._interval:
            return False
        self._last_tick_ts = now
        try:
            payload = self._snapshot()
            if payload is None:
                return False
            self._post(payload)
            self._consecutive_failures = 0
            return True
        except Exception as e:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._log:
                self._log.warning("glitch_ingest tick failed (%d): %s",
                                  self._consecutive_failures, e)
            return False

    # ── Snapshot construction ────────────────────────────────────────

    def _snapshot(self) -> Optional[dict[str, Any]]:
        """Read MT5 state into the ingest schema. Returns None when
        MT5 isn't connected — the caller throttle-counter still
        advances so we don't busy-spin on a closed terminal."""
        if mt5 is None:
            return None
        info = mt5.account_info()
        if info is None:
            return None
        positions = mt5.positions_get() or ()
        payload: dict[str, Any] = {
            "ctid_trader_account_id": self._login,
            "balance": float(info.balance),
            "equity":  float(info.equity),
            "open_positions": [self._map_position(p) for p in positions],
        }
        if self._firm_hint:
            payload["firm_hint"] = self._firm_hint
        if self._starting_balance_hint is not None:
            payload["starting_balance_hint"] = self._starting_balance_hint
        if self._tier_hint:
            payload["tier_hint"] = self._tier_hint
        return payload

    @staticmethod
    def _map_position(p: Any) -> dict[str, Any]:
        # MT5 POSITION_TYPE_BUY = 0, _SELL = 1
        side = "buy" if getattr(p, "type", 0) == 0 else "sell"
        return {
            "position_id":     int(getattr(p, "ticket", 0)),
            "symbol":          str(getattr(p, "symbol", "")),
            "side":            side,
            "volume":          float(getattr(p, "volume", 0)),
            "entry_price":     float(getattr(p, "price_open", 0)),
            "current_price":   float(getattr(p, "price_current", 0)) or None,
            "unrealized_pnl":  float(getattr(p, "profit", 0)),
            "swap":            float(getattr(p, "swap", 0)),
            # `time` is a unix int (seconds); convert to ISO 8601.
            "opened_at": (
                _utc_iso(int(p.time)) if getattr(p, "time", 0) else None
            ),
        }

    # ── HTTP ────────────────────────────────────────────────────────

    def _post(self, payload: dict[str, Any]) -> None:
        # Idempotency key: per-login per-minute. Same-minute retries
        # collapse to one stored row on the server side.
        minute = int(time.time() // 60)
        idem = f"mt5-{self._login}-{minute}"
        req = urllib.request.Request(
            url=f"{self._base_url}/v1/ingest/snapshot",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type":  "application/json",
                "Idempotency-Key": idem,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"ingest {resp.status}: {resp.read()[:200].decode(errors='replace')}")
                # Drain the body so the socket can be returned to the
                # urllib pool cleanly; we don't need the payload.
                resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()[:200].decode(errors="replace") if e.fp else ""
            raise RuntimeError(f"ingest {e.code}: {body}") from None


def _utc_iso(unix_seconds: int) -> str:
    """ISO 8601 string in UTC for `opened_at`. MT5 returns a POSIX
    timestamp; we treat it as UTC because that's what `mt5.account_
    info()` documents."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()
