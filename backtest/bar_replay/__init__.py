"""
Bar-replay simulator (Phase 2).

Replays historical OHLC bars through a pure-Python strategy +
position-manager + FundingPips Zero rules, so we can answer:

    "Does this strategy + this overlay survive the prop-firm rules?"

Mode A (tape replay, the original `backtest/runner.py`) used the
realised PnL of historical trades and only added risk-aware sizing.
That couldn't model the partial-TP overlay we need for FundingPips,
because partial TP changes the trade's PnL — you can't replay history
and pretend a different exit happened.

Mode B (this package) re-decides the trade. It walks bars chronologically,
runs the strategy on each closed bar, opens a virtual position when the
strategy says so, and the position manager handles fills, partial TPs,
trailing stops, and final close. The account.py + rules/ machinery from
Phase 1 stays — only the upstream changes.

Intentionally narrow scope: we replay ONE strategy at a time (the
trend_follower we ship as a cAlgo cBot on the Store). Multi-strategy
ensemble can come later. Single product first.
"""

__all__ = ["__version__"]
__version__ = "0.2.0"
