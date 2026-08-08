# glitch-trade-core

Engine libraries behind **Glitch Trade** (the Glitch Executor prop-firm trading
dashboard): a strategy **IR** (intermediate representation) layer and a bar-replay
**backtest** engine with prop-firm rule sets.

The Glitch Trade API imports these at **runtime** (`ir` and `backtest` are imported at
module load), so this repo is a **live dependency of the backend**, not a standalone
product. It is vendored into the API monorepo as a git submodule at
`api/vendor/glitch-trade-core` and installed into the API's image and virtualenv.

---

## Packages

### `ir/` — Strategy IR
A compact schema + compiler/runner for trading strategies.

| Module | Purpose |
| --- | --- |
| `schema.json` | The Strategy-IR JSON schema. |
| `quick_parse.py` | Parse a quick/inline strategy spec into IR. |
| `runner.py` | Validate + run IR — `trend-follower` and `quick-rule` shapes. |
| `compile.py` | Compile IR → cAlgo/cTrader C# cBot source. |
| `algo_pack.py` | Packaged-algo helpers. |
| `samples/` | Example IR documents. |

### `backtest/` — Bar-replay engine
Deterministic, bar-by-bar backtesting that is aware of prop-firm rules.

| Path | Purpose |
| --- | --- |
| `bar_replay/` | The simulator — `bars`, `indicators`, `strategy`, `sim`, `manager`. |
| `bar_replay/{sweep,walk_forward,ab_test}.py` | Standalone research CLIs (param sweep, walk-forward, A/B). |
| `rules/` | Prop-firm rule sets — FTMO, FundingPips, Apex, MFF, The5ers, FundedNext, GetLeveraged (daily-loss / drawdown / consistency gates). |
| `account.py`, `sizer.py`, `report.py`, `runner.py` | Account state, position sizing, reporting, CLI entry. |

---

## Install / use

As a dependency of the Glitch Trade API it is installed from the vendored submodule:

```bash
pip install ./vendor/glitch-trade-core
```

Standalone, for backtesting/research:

```bash
pip install -e .
python -m backtest --help
python -m backtest.bar_replay.sweep --symbol JPN225 --trials 200
```

See `pyproject.toml` for packages and dependencies.

---

## License

Licensed under the terms in [`LICENSE`](LICENSE); attribution/notices in
[`NOTICE`](NOTICE). Contribution guidance in [`CONTRIBUTING.md`](CONTRIBUTING.md).
