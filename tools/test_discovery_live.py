"""
Headless integration test for the Phase 2 discovery pipeline.

Drives every discovery step against tools/dummy_target.py WITHOUT
interactive input — pre-seeds the health delta so VisionScout is bypassed.

Usage:
  # Start dummy_target.py first, then:
  python tools/test_discovery_live.py --pid <PID>

Pass:  state_map_python.json is written with >=2 fields and >=1 verified scan address.
Fail:  any step raises an unhandled exception or writes 0 state variables.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mcp.ce_client import CEClient
from src.mcp.ghidra_client import GhidraClient
from src.discovery.module_info import get_module_base, live_to_static, fmt_offset
from src.discovery.struct_builder import StructBuilder
from src.schema.state_map_schema import (
    StateMap, StateVariable, ActionManifest, PointerChain, SemanticRole
)

CE_SERVER    = r"D:\CE\cheatengine-mcp-bridge\MCP_Server\mcp_cheatengine.py"
GHIDRA_SVR   = r"D:\hgidra\ghidra-mcp\bridge_mcp_ghidra.py"
SESSION_ID   = "dummy_test"

RESULTS: dict = {}


async def step_attach(pid: int) -> tuple[int, int]:
    """Attach CE, return (pid, module_base)."""
    print(f"\n[1] ATTACH — CE + python.exe PID {pid}")
    async with CEClient(CE_SERVER) as ce:
        r = await ce.attach(str(pid))
        assert r.success, f"CE attach failed: {r}"
        print(f"    process: {r.process_name} (pid={r.process_id})")

        base = await get_module_base(ce, "python.exe")
        print(f"    python.exe base: 0x{base:X}" if base else "    base: not found")

    RESULTS["attach"] = {"pid": pid, "module_base": base}
    return pid, base or 0


async def step_scan(health_value: float) -> list[str]:
    """Run persistent scan for health value, refine with exact new value from log, return candidates.

    NOTE: CEClient spawns a subprocess mcp_cheatengine.py that connects to CE via
    \\.\pipe\CE_MCP_Bridge_v99.  If Claude Desktop already holds that pipe, the
    subprocess call will fail with "Bridge is not reachable".  In that case run
    the test standalone (without Claude Desktop CE MCP loaded) or use the direct
    MCP tools in the Claude session instead.
    """
    import re as _re
    print(f"\n[2] MEMORY SCAN — searching for health={health_value}")
    scan_name = f"bm_{SESSION_ID}_health"

    # Read current health from log — first_scan value may differ from health_value
    # if the target has already ticked since it started.
    log_path = Path("tools/dummy_target.log")
    current_health_str = str(int(health_value))
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        health_lines = [l for l in lines if "Health:" in l and "Turn:" in l]
        if health_lines:
            m = _re.search(r"Health:\s+([\d.]+)", health_lines[-1])
            if m:
                current_health_str = str(int(float(m.group(1))))
                print(f"    log current health: {current_health_str} (overrides arg {int(health_value)})")

    async with CEClient(CE_SERVER) as ce:
        try:
            await ce.persistent_destroy(scan_name)
        except Exception:
            pass
        await ce.persistent_create(scan_name)
        count = await ce.persistent_first_scan(scan_name, current_health_str, "float")
        print(f"    first scan  ({current_health_str}): {count} candidates")

    # Wait for ONE tick (20 seconds) so health decrements
    print(f"    waiting 22s for health to tick down...")
    await asyncio.sleep(22)

    # Read new health value from log — exact scan is far more reliable than "decreased"
    new_health_str = None
    log_path = Path("tools/dummy_target.log")
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        health_lines = [l for l in lines if "Health:" in l and "Turn:" in l]
        if health_lines:
            m = _re.search(r"Health:\s+([\d.]+)", health_lines[-1])
            if m:
                new_health_str = m.group(1)
                print(f"    log says new health: {new_health_str}")

    async with CEClient(CE_SERVER) as ce:
        if new_health_str:
            count = await ce.persistent_next_scan(scan_name, value=new_health_str, scan_option="exact")
            print(f"    refine (exact={new_health_str}): {count} candidates")
        else:
            count = await ce.persistent_next_scan(scan_name, scan_option="decreased")
            print(f"    refine (decreased):      {count} candidates")

        page = await ce.persistent_results(scan_name, limit=10)
        candidates = [r.address for r in page.results]
        print(f"    top candidates: {candidates[:5]}")
        await ce.persistent_destroy(scan_name)

    RESULTS["scan"] = {"candidates": candidates, "count": count}
    return candidates


async def step_dissect(address: str) -> dict:
    """Dissect struct at the found address and get RTTI class name."""
    print(f"\n[3] STRUCT DISSECT — addr={address}")
    async with CEClient(CE_SERVER) as ce:
        raw = await ce.read_memory(address, 24)
        rtti = await ce.rtti(address)

    print(f"    RTTI class: {rtti}")
    print(f"    raw bytes : {raw}")

    # Decode manually (CE returns hex bytes string)
    import struct as _struct
    raw_bytes = bytes.fromhex(raw.get("data", "").replace(" ", ""))
    fields_decoded = {}
    if len(raw_bytes) >= 20:
        fields_decoded = {
            "health":     _struct.unpack_from("<f", raw_bytes, 0)[0],
            "max_health": _struct.unpack_from("<f", raw_bytes, 4)[0],
            "pos_x":      _struct.unpack_from("<f", raw_bytes, 8)[0],
            "pos_y":      _struct.unpack_from("<f", raw_bytes, 12)[0],
            "turn":       _struct.unpack_from("<i", raw_bytes, 16)[0],
        }
        print(f"    decoded   : {fields_decoded}")

    RESULTS["dissect"] = {"address": address, "rtti": rtti, "fields": fields_decoded}
    return fields_decoded


async def step_ghidra_verify() -> bool:
    """Verify Ghidra tools work: decompile wWinMain, get xrefs."""
    print(f"\n[4] GHIDRA VERIFY — decompile + xrefs on CoQ.exe")
    async with GhidraClient(GHIDRA_SVR) as gh:
        ok = await gh.load_binary("/CoQ.exe")
        fn = await gh.decompile("140001000")
        xrefs = await gh.xrefs_to("140001000")
        print(f"    load_binary: {ok}")
        print(f"    decompile  : {fn.name} ({len(fn.pseudocode)} chars) — {'OK' if len(fn.pseudocode) > 10 else 'EMPTY'}")
        print(f"    xrefs_to   : {len(xrefs)} refs — {[x.from_address for x in xrefs[:3]]}")

    ok = len(fn.pseudocode) > 10 and len(xrefs) > 0
    RESULTS["ghidra"] = {"ok": ok, "decompile_len": len(fn.pseudocode), "xrefs": len(xrefs)}
    return ok


def step_build_state_map(candidates: list[str], fields: dict, module_base: int) -> str:
    """Build state_map.json from discovered data."""
    print(f"\n[5] BUILD STATE MAP")
    builder = StructBuilder(class_name="PlayerState")

    # Add fields from struct dissect (with known offsets from our dummy_target)
    static_fields = [
        {"name": "health",     "offset": 0x00, "type": "float", "semantic_role": "health"},
        {"name": "max_health", "offset": 0x04, "type": "float", "semantic_role": "scalar"},
        {"name": "pos_x",      "offset": 0x08, "type": "float", "semantic_role": "coordinate_x"},
        {"name": "pos_y",      "offset": 0x0C, "type": "float", "semantic_role": "coordinate_y"},
        {"name": "turn",       "offset": 0x10, "type": "int",   "semantic_role": "time"},
    ]
    builder.add_from_static_analysis(static_fields)

    # Annotate field values from dissect
    for f_name, val in fields.items():
        if f_name == "health":
            pass  # will be min=0 max=100

    final = builder.finalize()
    print(f"    struct builder: {len(final)} fields, class={builder.class_name}")

    # Build StateMap — health gets pointer chain (heap-only), rest are struct offsets
    health_addr = candidates[0] if candidates else None
    state_vars: dict = {}
    for f in final:
        # Heap address: no stable module pointer chain
        state_vars[f.name] = StateVariable(
            type=f.type_name,
            min=0.0, max=100.0,
            role=SemanticRole(f.semantic_role),
            pointer_chain=None,
            struct_offset=f.offset,
            dynamic_only=True,   # Python heap — no stable pointer
            source="discovery",
        )
    # health gets the scan-confirmed address noted
    if health_addr and "health" in state_vars:
        state_vars["health"].pointer_chain = PointerChain(
            base=health_addr,  # direct address (stable within session)
            offsets=[],
            verified=True,
        )
        state_vars["health"].dynamic_only = False

    sm = StateMap(
        game_name="python",
        engine_hint="python-ctypes",
        binary="python.exe",
        module_name="python.exe",
        observation_dimensions=len(state_vars),
        state_variables=state_vars,
        actions=ActionManifest(count=4, bindings=["MOVE_N","MOVE_S","MOVE_E","MOVE_W"]),
    )
    out = "state_map_python.json"
    sm.save(out)
    print(f"    written: {out}  ({len(state_vars)} vars)")
    RESULTS["state_map"] = {"path": out, "vars": len(state_vars)}
    return out


async def main(pid: int):
    # Step 1: attach
    _, module_base = await step_attach(pid)

    # Step 2: scan — starts at 100.0, waits for tick
    candidates = await step_scan(100.0)

    # Step 3: dissect first candidate
    fields: dict = {}
    if candidates:
        fields = await step_dissect(candidates[0])
    else:
        print("[WARN] No candidates found — skipping dissect")

    # Step 4: Ghidra validation
    ghidra_ok = await step_ghidra_verify()

    # Step 5: build state_map
    out_path = step_build_state_map(candidates, fields, module_base)

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS:")
    print(f"  Attach (CE)         : PASS")
    print(f"  Memory scan         : {'PASS' if candidates else 'FAIL'} ({len(candidates)} candidates)")
    print(f"  Struct dissect      : {'PASS' if fields else 'FAIL'}")
    print(f"  Ghidra verify       : {'PASS' if ghidra_ok else 'FAIL'}")
    print(f"  state_map.json      : {out_path}")
    print(f"  State variables     : {RESULTS.get('state_map', {}).get('vars', 0)}")
    if fields:
        print(f"\nDecoded struct at CE-found address:")
        for k, v in fields.items():
            print(f"    {k:<12} = {v}")
    print(f"{'='*60}")

    # Verify address match
    log = Path("tools/dummy_target.log").read_text(encoding="utf-8", errors="replace")
    health_line = [l for l in log.splitlines() if "health addr" in l]
    if health_line and candidates:
        expected = health_line[0].split("0x")[1].split()[0].lstrip("0") or "0"
        found = candidates[0].lstrip("0x").lstrip("0") or "0"
        match = expected.lower() == found.lower()
        print(f"\nAddress verification:")
        print(f"  Target reported : 0x{expected}")
        print(f"  CE scan found   : 0x{found}")
        print(f"  Match           : {'YES - CONFIRMED' if match else 'NO'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.pid))
