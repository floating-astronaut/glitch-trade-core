"""
Glitch Trade Engine — backtesting & prop-firm simulator.

Purpose
-------
Given the historical signal + trade tape that the live `glitch-ml-collector`
service writes into the `glitch_ml` Postgres database, replay it through a
virtual cTrader account governed by a configurable prop-firm rule set and
report whether the engine would have survived.

Scope
-----
Phase 1 (this module): *tape replay* mode. We use the realised PnL recorded
on each `ml_trades` row as ground truth and only add the layers the live
engine doesn't have today — risk-aware position sizing, oracle netting,
calendar/news vetoes, trailing-drawdown breach detection.

Phase 2 (future): *bar replay* mode that re-evaluates each bot's signal
function against `ml_bars` and lets the simulator decide which trades open
and where the stops sit.

Read-only against the production database. No bot configs, broker creds, or
live service files are touched.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
