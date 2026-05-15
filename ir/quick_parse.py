"""
Quick-rule grammar — natural-language → IR.

v1 is a deterministic pattern matcher, NOT an LLM. We trade
expressiveness for predictability so a typo doesn't silently
deploy a wrong-direction trade. Once we have telemetry on what
patterns users actually type, an LLM-assist layer can re-rank
unparsed inputs and suggest a canonical form to confirm.

Patterns covered in v1:

  buy   <SYMBOL> at <PRICE>, sell at <PRICE>
  sell  <SYMBOL> at <PRICE>, buy back at <PRICE>     (short)
  long  <SYMBOL> when price >= <PRICE>, exit at <PRICE>
  short <SYMBOL> when price <= <PRICE>, exit at <PRICE>

Optional size suffix:    "  with 0.01 units"  /  "  with 0.5% risk"

Anything else returns ParseError; the UI shows example chips.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class ParseError(ValueError):
    """Raised when the input doesn't match any v1 grammar pattern."""


@dataclass
class _Match:
    side: str         # "long" or "short"
    symbol: str
    entry_price: float
    exit_price: float
    size: dict[str, float] | None


# A single regex covers the four canonical patterns. `(?i)` for case
# insensitivity. Symbol is alphanumeric (BTCUSD, EURUSD, US500, JPN225).
_PRICE = r"(?:\$?\s*)(\d+(?:\.\d+)?)"
_PATTERNS = [
    # buy SYMBOL at P1, sell at P2
    (re.compile(rf"(?i)^\s*buy\s+([A-Z0-9]+)\s+(?:at|@)\s+{_PRICE}\s*[,;]\s*sell(?:\s+at)?\s+{_PRICE}\s*(.*)$"), "long"),
    # sell SYMBOL at P1, buy back at P2 (short)
    (re.compile(rf"(?i)^\s*sell\s+([A-Z0-9]+)\s+(?:at|@)\s+{_PRICE}\s*[,;]\s*buy(?:\s+back)?(?:\s+at)?\s+{_PRICE}\s*(.*)$"), "short"),
    # long SYMBOL when price >= P1, exit at P2
    (re.compile(rf"(?i)^\s*long\s+([A-Z0-9]+)\s+(?:when\s+)?(?:price\s*)?(?:>=|≥|above|hits|reaches)\s+{_PRICE}\s*[,;]\s*(?:exit|close|sell)(?:\s+at)?\s+{_PRICE}\s*(.*)$"), "long"),
    # short SYMBOL when price <= P1, exit at P2
    (re.compile(rf"(?i)^\s*short\s+([A-Z0-9]+)\s+(?:when\s+)?(?:price\s*)?(?:<=|≤|below|hits|reaches)\s+{_PRICE}\s*[,;]\s*(?:exit|close|cover|buy)(?:\s+at)?\s+{_PRICE}\s*(.*)$"), "short"),
]

_SIZE_PATTERNS = [
    (re.compile(r"(?i)with\s+(\d+(?:\.\d+)?)\s+units?"),         lambda v: {"fixed_units": float(v)}),
    (re.compile(r"(?i)with\s+(\d+(?:\.\d+)?)\s+lots?"),          lambda v: {"fixed_lots":  float(v)}),
    (re.compile(r"(?i)with\s+(\d+(?:\.\d+)?)\s*%\s*risk"),       lambda v: {"risk_per_trade_pct": float(v) / 100.0}),
]


def _parse_size(suffix: str) -> dict[str, float] | None:
    suffix = suffix.strip(" .,;")
    if not suffix:
        return None
    for pat, builder in _SIZE_PATTERNS:
        m = pat.search(suffix)
        if m:
            return builder(m.group(1))
    return None


def parse(text: str) -> _Match:
    """Try every v1 pattern; return the first match. Raise ParseError otherwise."""
    for pat, side in _PATTERNS:
        m = pat.match(text)
        if m:
            symbol, p1, p2, suffix = m.groups()
            size = _parse_size(suffix)
            entry = float(p1)
            exit_ = float(p2)
            # For shorts, allow either order (entry > exit, since we sell high & buy low).
            return _Match(side=side, symbol=symbol.upper(),
                          entry_price=entry, exit_price=exit_, size=size)
    raise ParseError(
        f"Couldn't parse: {text!r}. Try patterns like:\n"
        "  • buy BTCUSD at 80000, sell at 81000\n"
        "  • sell EURUSD at 1.10, buy back at 1.09\n"
        "  • long XAUUSD when price >= 2050, exit at 2080"
    )


def to_ir(text: str, *, name: str | None = None) -> dict[str, Any]:
    """Parse a quick-rule one-liner and return a complete, schema-valid IR."""
    m = parse(text)
    name = name or f"{m.symbol} quick rule"

    side_op = ">=" if m.side == "long" else "<="
    entry_when = f"price {side_op} {m.entry_price}"

    # Exit triggers when price reaches the target — the inverse comparison
    # for shorts (we want price to fall back to exit_price).
    exit_op = ">=" if m.side == "long" else "<="
    exit_when = f"price {exit_op} {m.exit_price}"

    entry: dict[str, Any] = {"side": m.side, "when": entry_when}
    if m.size is not None:
        entry["size"] = m.size

    return {
        "name": name,
        "description": f"Auto-parsed from quick rule: {text!r}",
        "version": 1,
        "tags": ["quick-rule", "price-trigger"],
        "instruments": [{"symbol": m.symbol, "timeframe": "tick"}],
        "entries": [entry],
        "exits":   [{"type": "limit", "when": exit_when}],
        "guards":  {"firm_rules": None},
    }


# CLI for sanity-checking / dogfooding.
if __name__ == "__main__":
    import sys, json as _json
    if len(sys.argv) < 2:
        print("usage: python -m ir.quick_parse \"buy BTCUSD at 80000, sell at 81000\"")
        sys.exit(2)
    text = " ".join(sys.argv[1:])
    try:
        ir = to_ir(text)
    except ParseError as e:
        print(f"PARSE ERROR\n{e}")
        sys.exit(1)
    print(_json.dumps(ir, indent=2))
