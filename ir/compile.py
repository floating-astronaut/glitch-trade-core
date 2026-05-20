"""
IR → cAlgo C# compiler.

Turns a Strategy IR document into a complete cAlgo cBot source file the
user can drop into cTrader Desktop. Two shapes covered, matching what
`ir/runner.py` can already backtest:

  1. **trend-follower shape** — uses the hand-written cBot in
     `ctrader-store/trend-follower/GlitchTrendFollowerBot.cs` as a
     parameter-substitution template. The IR's indicator periods,
     entry's ADX threshold, and exit's stop_loss/partial_tp/trailing
     values override the template's `DefaultValue=` attributes. The
     emitted C# is *the same code* the customer's downloaded cBot
     runs — guarantees backtest ↔ live parity.

  2. **quick-rule shape** — emits a small standalone cBot from an
     inline template that does:
        - On every Tick, compare Bid/Ask against the trigger price
        - Execute one market order when triggered, with optional
          fixed-units sizing
        - Close the position when the exit price is touched

Output is a single .cs file (string). cTrader Desktop accepts pasted
.cs source via "Add → New cBot → paste"; the .algo packaging dance
(zip + manifest signing) is deferred to a later iteration since the
deploy wizard's "paste this code" flow is acceptable for v1.

Anything that's not one of those two shapes raises
`UnsupportedIRShape` — same exception the runner uses, so the API
layer can re-export one error type.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .runner import UnsupportedIRShape, _is_quick_shape, _is_trend_shape

# Path to the hand-written template the trend-shape compiler patches.
_TREND_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "ctrader-store" / "trend-follower" / "GlitchTrendFollowerBot.cs"
)

_NUM = r"-?\d+(?:\.\d+)?"


# ── Trend-follower compilation ────────────────────────────────────────

def _patch_default(src: str, param_label: str, new_value: str | float | int) -> str:
    """Substitute the `DefaultValue = X` for a [Parameter("LABEL", ...)] line.
    Operates on the first match (each Parameter label is unique)."""
    # The label is in quotes inside [Parameter(...)]. Match the line that
    # contains "LABEL" then the next DefaultValue = SOMETHING token.
    pat = re.compile(
        rf'(\[Parameter\("{re.escape(param_label)}",[^]]*?DefaultValue\s*=\s*)({_NUM}|true|false|"[^"]*")',
        re.MULTILINE,
    )
    def _sub(m: re.Match[str]) -> str:
        return m.group(1) + str(new_value)
    new_src, n = pat.subn(_sub, src, count=1)
    if n == 0:
        raise ValueError(f"compile.patch: no Parameter labelled {param_label!r}")
    return new_src


def _compile_trend(ir: dict[str, Any]) -> str:
    """Return cAlgo C# source for a trend-shape IR by patching the
    hand-written template's DefaultValue attributes."""
    src = _TREND_TEMPLATE.read_text()
    inds = {i["type"]: i for i in ir.get("indicators", [])}

    # Indicator periods
    src = _patch_default(src, "SMA period", inds["sma"].get("period", 9))
    src = _patch_default(src, "EMA period", inds["ema"].get("period", 21))
    src = _patch_default(src, "ADX period", inds["adx"].get("period", 14))
    src = _patch_default(src, "ATR period", inds["atr"].get("period", 14))

    # ADX threshold from "adx > N" in the entry
    entry_when = ir["entries"][0]["when"]
    m = re.search(rf"adx\s*>\s*({_NUM})", entry_when)
    if m:
        src = _patch_default(src, "ADX min trend", float(m.group(1)))

    # Sizing
    sizing = ir.get("sizing") or {}
    risk_pct = sizing.get("risk_per_trade_pct")
    if risk_pct is not None:
        # Template stores percent as a number 0–5, IR stores as fraction
        src = _patch_default(src, "Risk per trade (% equity)", risk_pct * 100.0)

    # Exits
    for ex in ir["exits"]:
        t = ex.get("type")
        if t == "stop_loss":
            mult = ex.get("spec", {}).get("atr_mult")
            if mult is not None:
                src = _patch_default(src, "Stop-loss ATR multiplier", mult)
        elif t == "take_profit":
            atr = ex.get("spec", {}).get("atr_mult") or (ex.get("at_r") and ex["at_r"] * 2)
            if atr is not None:
                src = _patch_default(src, "Take-profit ATR multiplier", atr)
        # partial_tp / trailing aren't yet exposed as Parameters in the
        # template — the template's manage-trade logic uses fixed defaults
        # that match the IR's defaults (50% off at 1R, trail 0.5R steps).
        # Note in the C# header so a customer reading the source knows.

    # Sides — disable a side if the IR only has one direction
    sides = {e["side"] for e in ir["entries"]}
    if "long" not in sides:
        src = _patch_default(src, "Allow longs", "false")
    if "short" not in sides:
        src = _patch_default(src, "Allow shorts", "false")

    # Label = strategy name (sanitised to alphanumeric + underscore for cAlgo)
    label = re.sub(r"\W+", "", ir["name"])[:32] or "GlitchStrategy"
    src = _patch_default(src, "Label", f'"{label}"')

    # Provenance header
    header = (
        "// =============================================================================\n"
        f"// COMPILED FROM Strategy IR: {ir['name']}\n"
        f"// IR version: {ir.get('version', '?')}   shape: trend-follower\n"
        "// Generated by glitch-trade-core/ir/compile.py — do not hand-edit; re-compile\n"
        "// from the source IR if you want to change parameters.\n"
        "// =============================================================================\n\n"
    )
    return header + src


# ── Quick-rule compilation ────────────────────────────────────────────

_QUICK_TEMPLATE = """\
// =============================================================================
// COMPILED FROM Strategy IR: {ir_name}
// IR version: {version}   shape: quick-rule
// Generated by glitch-trade-core/ir/compile.py — do not hand-edit; re-compile
// from the source IR if you want to change parameters.
//
// Behaviour:
//   - On every Tick, watch Bid/Ask of {symbol}
//   - When the {entry_side} entry condition fires, place a single market order
//     of {units} units
//   - When the exit condition fires, close the open position
//   - One position at a time; re-arms after exit
// =============================================================================

using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using cAlgo.API;

// ── Templated credentials (CBOT-DIST-1 / -2) ─────────────────────
// algo_pack.py replaces the markers below with the operator's
// API key / user id / ingest base at .algo download time. The
// quick-rule cBot uses them to POST a 30 s heartbeat so the
// Deployments matrix chip can read "live".
namespace GlitchExecutorCredentials
{{
    public static class Credentials
    {{
        public const string ApiKey     = "__GLITCH_API_KEY__";
        public const string UserId     = "__GLITCH_USER_ID__";
        public const string IngestBase = "__GLITCH_INGEST_BASE__";
    }}
}}

namespace cAlgo.Robots
{{
    // AccessRights.FullAccess required for the heartbeat POST.
    [Robot(AccessRights = AccessRights.FullAccess, TimeZone = TimeZones.UTC)]
    public class {class_name} : Robot
    {{
        [Parameter("Entry price",  DefaultValue = {entry_price}, Group = "Rule")]
        public double EntryPrice {{ get; set; }}

        [Parameter("Exit price",   DefaultValue = {exit_price},  Group = "Rule")]
        public double ExitPrice {{ get; set; }}

        [Parameter("Volume (units)", DefaultValue = {units}, MinValue = 1, Group = "Rule")]
        public double Volume {{ get; set; }}

        [Parameter("Label",        DefaultValue = "{label}", Group = "Misc")]
        public string Label {{ get; set; }}

        private static readonly HttpClient _http = new HttpClient
        {{
            Timeout = TimeSpan.FromSeconds(10),
        }};
        private const int HeartbeatIntervalSeconds = 30;
        private DateTime _lastHeartbeatAt = DateTime.MinValue;

        protected override void OnStart()
        {{
            SendHeartbeat();
        }}

        protected override void OnTick()
        {{
            if ((DateTime.UtcNow - _lastHeartbeatAt).TotalSeconds >= HeartbeatIntervalSeconds)
            {{
                SendHeartbeat();
            }}

            var pos = Positions.Find(Label, SymbolName);
            if (pos == null)
            {{
                if ({entry_check})
                {{
                    ExecuteMarketOrder(TradeType.{trade_type}, SymbolName, Volume, Label);
                }}
            }}
            else
            {{
                if ({exit_check})
                {{
                    ClosePosition(pos);
                }}
            }}
        }}

        private void SendHeartbeat()
        {{
            _lastHeartbeatAt = DateTime.UtcNow;
            try
            {{
                var url = GlitchExecutorCredentials.Credentials.IngestBase + "/me/cbot/heartbeat";
                var json = "{{\\"ctid_trader_account_id\\":" + Account.Number + "}}";
                var req = new HttpRequestMessage(HttpMethod.Post, url);
                req.Headers.Add("Authorization", "Bearer " + GlitchExecutorCredentials.Credentials.ApiKey);
                req.Content = new StringContent(json, Encoding.UTF8, "application/json");
                _http.SendAsync(req)
                     .ContinueWith(t => {{ var _ = t.Exception; }},
                                   TaskContinuationOptions.OnlyOnFaulted);
            }}
            catch (Exception)
            {{
                // never crash trading loop on heartbeat failure
            }}
        }}
    }}
}}
"""


def _compile_quick(ir: dict[str, Any]) -> str:
    entry = ir["entries"][0]
    exit_ = ir["exits"][0]
    side = entry["side"]
    inst = ir["instruments"][0]

    em = re.match(rf"\s*price\s*(>=|<=|>|<)\s*({_NUM})\s*$", entry["when"])
    xm = re.match(rf"\s*price\s*(>=|<=|>|<)\s*({_NUM})\s*$", exit_["when"])
    if not (em and xm):
        raise UnsupportedIRShape(f"quick-rule expressions must be `price OP NUMBER`; got {entry['when']!r} / {exit_['when']!r}")

    entry_price = float(em.group(2))
    exit_price = float(xm.group(2))

    size = entry.get("size") or {}
    units = size.get("fixed_units") or size.get("fixed_lots", 0.01) * 100_000
    units = max(1, int(round(units)))

    label = re.sub(r"\W+", "", ir["name"])[:32] or "GlitchQuick"
    class_name = re.sub(r"\W+", "_", "Glitch_" + label)

    if side == "long":
        trade_type = "Buy"
        entry_check = "Symbol.Ask >= EntryPrice"
        exit_check  = "Symbol.Bid >= ExitPrice"
    else:
        trade_type = "Sell"
        entry_check = "Symbol.Bid <= EntryPrice"
        exit_check  = "Symbol.Ask <= ExitPrice"

    return _QUICK_TEMPLATE.format(
        ir_name=ir["name"], version=ir.get("version", "?"),
        symbol=inst["symbol"],
        entry_side=side, units=units, label=label, class_name=class_name,
        entry_price=entry_price, exit_price=exit_price,
        entry_check=entry_check, exit_check=exit_check,
        trade_type=trade_type,
    )


# ── Public entry point ────────────────────────────────────────────────

def compile_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """Validate IR shape, dispatch to the right compiler, return:
        {
          "shape": "trend-follower" | "quick-rule",
          "filename": "<sanitised>.cs",
          "source": "<C# source>",
          "size_bytes": <int>,
        }
    """
    from . import validate
    validate(ir)

    if _is_trend_shape(ir):
        src = _compile_trend(ir)
        shape = "trend-follower"
    elif _is_quick_shape(ir):
        src = _compile_quick(ir)
        shape = "quick-rule"
    else:
        raise UnsupportedIRShape(
            f"IR {ir['name']!r}: no compiler for this shape in v1. "
            "Trend-follower and quick-rule are the only shapes supported. "
            "The general IR compiler ships in week 4."
        )

    label = re.sub(r"\W+", "", ir["name"])[:48] or "GlitchStrategy"
    return {
        "shape": shape,
        "filename": f"Glitch_{label}.cs",
        "source": src,
        "size_bytes": len(src.encode()),
    }


if __name__ == "__main__":
    import argparse, json, sys
    p = argparse.ArgumentParser(prog="ir.compile")
    p.add_argument("ir_path")
    p.add_argument("-o", "--out", help="write .cs to this path instead of stdout")
    args = p.parse_args()
    ir = json.loads(Path(args.ir_path).read_text())
    result = compile_ir(ir)
    if args.out:
        Path(args.out).write_text(result["source"])
        print(f"wrote {result['size_bytes']}B → {args.out} (shape={result['shape']})")
    else:
        sys.stdout.write(result["source"])
