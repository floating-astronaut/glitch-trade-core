"""
.algo bundle packer — wraps `compile_ir` output into a cTrader
Desktop-installable `.algo` bundle that's already keyed to a single
operator's API credentials.

CBOT-DIST-1 (2026-05-19), per PRODUCT_ROADMAP_V2.md §1 Phase 2.

Why a packer + key injection (vs. just shipping `.cs` like today):
  - cTrader Desktop's "Add cBot" UX prefers `.algo` over copy-paste
    `.cs` — fewer wrong clicks, no compile-it-yourself step.
  - The cBot needs to call our `/v1/me/snapshot` ingest + (CBOT-DIST-2)
    heartbeat endpoints. Hard-coding API_KEY + USER_ID into the
    emitted source per-download means the operator doesn't have to
    paste anything after the install.

`.algo` is a zip archive that cTrader Desktop accepts via the
"Add → Add cBot from File" dialog. The minimum-viable layout we ship:

  Glitch_<Name>_v<N>.algo  (zip)
    ├── extension.json         ← bundle metadata, version, sources list
    ├── source/<filename>.cs   ← the compiled C#, with credentials inlined
    └── README.txt             ← what this is, how to enable it

cTrader Desktop opens the bundle, lists the source file, and offers
to compile it locally — same UX as "Add cBot from file" with a
single .cs, but pre-wrapped so the operator picks one file, not three.

Note on .dll signing: a fully-baked production .algo is a compiled
DLL + signed manifest. We deliberately ship source-form .algo for
v1 because (a) signing keys aren't set up yet and (b) the
source-form bundle works in cTrader Desktop today. The compiled-DLL
path is a separate future lane; the API surface here doesn't change
when that lands.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from .compile import compile_ir


# Sentinel constants we patch into the emitted C# so the cBot can
# call our ingest API without a manual paste. The compiler emits
# placeholder values that get overwritten here per-download. If a
# future compiler change moves these names, the regex below must
# move with it.
_API_KEY_MARKER = "__GLITCH_API_KEY__"
_USER_ID_MARKER = "__GLITCH_USER_ID__"
_INGEST_BASE_MARKER = "__GLITCH_INGEST_BASE__"


def _inject_credentials(
    cs_source: str,
    api_key: str,
    user_id: str,
    ingest_base: str,
) -> str:
    """Replace credential placeholders in the compiled C# with the
    caller's real values. We append a small `// glitch-credentials`
    constants block at the top of the file if the markers don't
    already appear in the source — older trend-shape templates
    don't carry them and we want every emitted bundle to be
    self-contained regardless of source template age."""
    if _API_KEY_MARKER in cs_source:
        out = cs_source.replace(_API_KEY_MARKER, api_key)
        out = out.replace(_USER_ID_MARKER, user_id)
        out = out.replace(_INGEST_BASE_MARKER, ingest_base)
        return out

    # Marker-free template — prepend a constants block under the
    # `using` section so the cBot can read it. The block is inert
    # if the cBot itself doesn't reference it, so it's harmless on
    # legacy templates and immediately useful on credential-aware
    # ones (CBOT-DIST-2).
    header = (
        f"// === Glitch Executor credentials (injected per download) ===\n"
        f"// User: {user_id}\n"
        f"// Issued: {datetime.now(timezone.utc).isoformat()}\n"
        f"namespace GlitchExecutorCredentials {{\n"
        f"    public static class Credentials {{\n"
        f"        public const string ApiKey = \"{api_key}\";\n"
        f"        public const string UserId = \"{user_id}\";\n"
        f"        public const string IngestBase = \"{ingest_base}\";\n"
        f"    }}\n"
        f"}}\n\n"
    )
    return header + cs_source


def _build_extension_json(
    strategy_name: str,
    version: int,
    cs_filename: str,
    shape: str,
) -> str:
    """cTrader bundle manifest. Schema is loose; cTrader Desktop
    accepts any well-formed JSON that names the source file and
    metadata fields. Fields below are the ones the Desktop UI
    actually surfaces."""
    return json.dumps(
        {
            "name": f"Glitch_{strategy_name}",
            "version": f"1.0.{version}",
            "publisher": "Glitch Executor",
            "type": "cBot",
            "shape": shape,
            "sources": [f"source/{cs_filename}"],
            "compiled_at": datetime.now(timezone.utc).isoformat(),
        },
        indent=2,
    )


def _build_readme(strategy_name: str, version: int, shape: str) -> str:
    return (
        f"Glitch Executor — {strategy_name}\n"
        f"==================================\n\n"
        f"Shape   : {shape}\n"
        f"Version : 1.0.{version}\n"
        f"Bundle  : Glitch_{strategy_name}_v{version}.algo\n\n"
        f"To install:\n"
        f"  1. Open cTrader Desktop.\n"
        f"  2. Automate tab → Add cBot → Add cBot from File.\n"
        f"  3. Pick this .algo file. cTrader compiles it locally.\n"
        f"  4. Drag the new cBot onto a chart of the symbol it should\n"
        f"     trade. Start the cBot.\n\n"
        f"This bundle is keyed to your Glitch Executor account.\n"
        f"Do not share — the embedded API key would let anyone push\n"
        f"snapshots and heartbeats under your account.\n"
    )


def pack_algo(
    ir: dict[str, Any],
    api_key: str,
    user_id: str,
    ingest_base: str = "https://glitchexecutor.com/api/v1",
    version: int = 1,
) -> dict[str, Any]:
    """Compile an IR, inject the caller's credentials, and zip the
    result into a .algo bundle. Returns:
        {
            "shape": "trend-follower" | "quick-rule",
            "filename": "Glitch_<Name>_v<N>.algo",
            "bytes": <bytes>,
            "size_bytes": <int>,
            "cs_filename": "<sanitised>.cs",
        }
    """
    compiled = compile_ir(ir)
    cs_source = _inject_credentials(
        compiled["source"], api_key, user_id, ingest_base
    )

    strategy_name = re.sub(r"\W+", "", ir["name"])[:48] or "Strategy"
    bundle_filename = f"Glitch_{strategy_name}_v{version}.algo"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "extension.json",
            _build_extension_json(strategy_name, version, compiled["filename"], compiled["shape"]),
        )
        z.writestr(f"source/{compiled['filename']}", cs_source)
        z.writestr("README.txt", _build_readme(strategy_name, version, compiled["shape"]))

    data = buf.getvalue()
    return {
        "shape": compiled["shape"],
        "filename": bundle_filename,
        "bytes": data,
        "size_bytes": len(data),
        "cs_filename": compiled["filename"],
    }
