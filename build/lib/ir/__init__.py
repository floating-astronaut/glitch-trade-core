"""
Strategy IR — the load-bearing abstraction across Glitch Trade.

The IR is a JSON document validated against `schema.json`. Every
component reads/writes the same shape:

  - visual builder writes IR
  - code editor parses + emits IR (best-effort round-trip)
  - compiler reads IR, emits cAlgo C# (`compile_ir.py`, week 3)
  - bar_replay backtester runs IR directly (no compile step needed)
  - marketplace stores IR alongside compiled .algo
  - firm-rule linter operates on IR-level annotations (`guards.firm_rules`)

This package is intentionally tiny — schema + validator + sample IRs
+ a bar_replay adapter. The compiler and the natural-language parser
live elsewhere (`compile_ir.py`, `quick_parse.py`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
    _HAVE_JSONSCHEMA = True
except ImportError:
    _HAVE_JSONSCHEMA = False

_SCHEMA_PATH = Path(__file__).parent / "schema.json"

with _SCHEMA_PATH.open() as f:
    SCHEMA: dict[str, Any] = json.load(f)


def validate(ir: dict[str, Any]) -> None:
    """Raise ValueError if `ir` doesn't conform to the IR schema."""
    if not _HAVE_JSONSCHEMA:
        # Soft-validate: just check the required top-level keys are
        # present so we still catch obvious typos.
        for key in ("name", "version", "instruments", "entries", "exits"):
            if key not in ir:
                raise ValueError(f"IR missing required field: {key!r}")
        return
    try:
        jsonschema.validate(ir, SCHEMA)
    except jsonschema.ValidationError as e:
        raise ValueError(f"IR validation failed: {e.message} (at {list(e.absolute_path)})") from e


__all__ = ["SCHEMA", "validate"]
