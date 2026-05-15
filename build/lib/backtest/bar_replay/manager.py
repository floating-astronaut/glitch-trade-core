"""
Position manager with partial-TP overlay.

Walks bars forward from a Signal and decides exit. Implements a
prop-firm-friendly overlay:

  - ATR-based SL at sl_atr_mult × ATR(at-entry)
  - First TP at tp1_r × R (R = SL distance), closes `tp1_fraction` of
    the position
  - Remainder runs with a trailing stop:
      * after tp1_r is hit, SL ratchets to entry (break-even)
      * thereafter, every additional 1R of favourable move bumps the SL
        by `trail_step_r` (default 0.5R), so on a 5R winner the trail
        captures most of it
  - Hard time exit at `max_hold_bars` to prevent leaving a position
    open across the weekend close (FundingPips Zero requires flat by
    Fri close)

Returns the realised dollar-PnL on a $1-per-pip basis (the simulator
converts to account units via the sizer). Per-trade structure includes
which exit fired so the report can attribute outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .strategy import Signal


@dataclass(frozen=True)
class ManagerParams:
    sl_atr_mult: float = 1.5
    tp1_r: float = 1.0
    tp1_fraction: float = 0.5
    trail_step_r: float = 0.5
    max_hold_bars: int = 96      # 96 × h1 = 4 days
    min_confidence: float = 0.60


@dataclass
class TradeResult:
    open_idx: int
    close_idx: int
    side: int                # +1 long, -1 short
    entry: float
    sl_at_entry: float
    tp1_at_entry: float
    pnl_per_lot: float       # in PRICE units; sizer scales to $
    exit_reason: str         # 'tp1_then_trail' | 'sl' | 'time' | 'tp1_only'
    bars_held: int
    hit_tp1: bool


def manage_trade(bars: np.ndarray, sig: Signal, p: ManagerParams) -> TradeResult | None:
    """Open a position at the open of bar (sig.idx + 1) and walk forward
    until exit. Returns None if the signal can't be acted on (no next
    bar, missing ATR, confidence below floor)."""
    if sig.vote == 0:                                 return None
    if sig.confidence < p.min_confidence:             return None
    if sig.atr <= 0:                                  return None
    open_idx = sig.idx + 1
    if open_idx >= bars.size:                         return None

    side = sig.vote
    entry = float(bars[open_idx]["o"])
    sl_dist = sig.atr * p.sl_atr_mult
    if sl_dist <= 0: return None

    if side == 1:
        sl  = entry - sl_dist
        tp1 = entry + sl_dist * p.tp1_r
    else:
        sl  = entry + sl_dist
        tp1 = entry - sl_dist * p.tp1_r

    hit_tp1 = False
    pnl_pre_tp1 = 0.0       # PnL realised on the partial close at tp1
    end = min(bars.size, open_idx + p.max_hold_bars)

    for i in range(open_idx, end):
        h = float(bars[i]["h"])
        l = float(bars[i]["l"])

        if side == 1:
            sl_hit  = l <= sl
            tp1_hit = (not hit_tp1) and h >= tp1
            # Order ambiguity: if both fire the same bar we conservatively
            # assume SL hit first (worst case for us → conservative test).
            if sl_hit:
                # Two scenarios: pre-TP1 (full size on SL) or post-TP1
                # (partial size on SL → the partial gain is locked in).
                if hit_tp1:
                    realised = pnl_pre_tp1 + (1 - p.tp1_fraction) * (sl - entry)
                    return TradeResult(
                        open_idx, i, side, entry, sl, tp1, realised,
                        "tp1_then_trail", i - open_idx + 1, True,
                    )
                realised = (sl - entry)  # full size, full SL
                return TradeResult(
                    open_idx, i, side, entry, sl, tp1, realised,
                    "sl", i - open_idx + 1, False,
                )
            if tp1_hit:
                hit_tp1 = True
                pnl_pre_tp1 = p.tp1_fraction * (tp1 - entry)
                # Move SL to break-even on the runner.
                sl = entry
                # Begin trailing: every full additional R above tp1
                # ratchets SL by trail_step_r * R.
                while h >= tp1 + sl_dist * p.trail_step_r:
                    tp1 += sl_dist * p.trail_step_r
                    sl  += sl_dist * p.trail_step_r
        else:  # short
            sl_hit  = h >= sl
            tp1_hit = (not hit_tp1) and l <= tp1
            if sl_hit:
                if hit_tp1:
                    realised = pnl_pre_tp1 + (1 - p.tp1_fraction) * (entry - sl)
                    return TradeResult(
                        open_idx, i, side, entry, sl, tp1, realised,
                        "tp1_then_trail", i - open_idx + 1, True,
                    )
                realised = (entry - sl)
                return TradeResult(
                    open_idx, i, side, entry, sl, tp1, realised,
                    "sl", i - open_idx + 1, False,
                )
            if tp1_hit:
                hit_tp1 = True
                pnl_pre_tp1 = p.tp1_fraction * (entry - tp1)
                sl = entry
                while l <= tp1 - sl_dist * p.trail_step_r:
                    tp1 -= sl_dist * p.trail_step_r
                    sl  -= sl_dist * p.trail_step_r

    # Time exit: close the runner at the last bar's close.
    last_close = float(bars[end - 1]["c"])
    if hit_tp1:
        runner = (last_close - entry) if side == 1 else (entry - last_close)
        realised = pnl_pre_tp1 + (1 - p.tp1_fraction) * runner
        reason = "tp1_then_time"
    else:
        realised = (last_close - entry) * side
        reason = "time"
    return TradeResult(
        open_idx, end - 1, side, entry, sl, tp1, realised,
        reason, end - 1 - open_idx + 1, hit_tp1,
    )
