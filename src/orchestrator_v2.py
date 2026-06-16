"""
Bridge-Maker Orchestrator v2 — Universal Grey-Box Discovery Pipeline.

Drives a hierarchical Scout/General swarm over CE MCP + Ghidra MCP to produce
state_map.json for any Windows game binary without game-specific code.

Nodes (LangGraph StateGraph):
  attach -> vision_scout -> memory_scout -> pointer_scout ->
  struct_scout -> static_scout -> pattern_scout -> synthesize
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------
try:
    from langgraph.graph import StateGraph, END
    _LANGGRAPH_OK = True
except ImportError:
    _LANGGRAPH_OK = False

    class StateGraph:  # type: ignore
        def __init__(self, *a, **kw): pass
        def add_node(self, *a, **kw): pass
        def add_edge(self, *a, **kw): pass
        def add_conditional_edges(self, *a, **kw): pass
        def set_entry_point(self, *a, **kw): pass
        def compile(self): return None
    END = "__end__"

# ---------------------------------------------------------------------------
# Project imports — Scout factories aliased to avoid collision with node names
# ---------------------------------------------------------------------------
from src.mcp.ce_client import CEClient
from src.mcp.ghidra_client import GhidraClient
from src.agents.scout_client import (
    GroqScout,
    MemoryScanOutput, PointerChainOutput, StructAnalysisOutput,
    StaticAnalysisOutput, ActionManifestOutput, SynthesisJudgment,
    memory_scout    as mk_memory_scout,
    pointer_scout   as mk_pointer_scout,
    struct_scout    as mk_struct_scout,
    static_scout    as mk_static_scout,
    action_scout    as mk_action_scout,
    general_synthesizer as mk_general,
)
from src.agents.vlm_client import VLMClient
from src.schema.state_map_schema import (
    StateMap, StateVariable, ActionManifest,
    PointerChain as SMPointerChain, SemanticRole,
)
from src.discovery.scan_session import scan_all_fields_parallel
from src.discovery.module_info import get_module_base, live_to_static, fmt_offset, parse_addr
from src.discovery.struct_builder import StructBuilder
from src.discovery.state_persistence import save_checkpoint, node_should_skip


# ---------------------------------------------------------------------------
# Session State TypedDict
# ---------------------------------------------------------------------------
from typing import TypedDict

class SessionState(TypedDict, total=False):
    # Config (from session.yaml)
    session_id: str
    game_exe: str
    game_window_title: str
    module_name: str
    ghidra_binary_path: str
    scan_type: str
    seed_deltas: list[dict]
    log_file: Optional[str]
    ce_server_path: str
    ghidra_server_path: str
    python_exe: str
    dry_run: bool
    resume: bool

    # Discovery results
    module_base: Optional[int]
    observed_deltas: list[dict]
    scan_candidates: dict           # {field: [address_str, ...]}
    pointer_chains: dict            # {field: {base, offsets, verified}}
    raw_struct: Optional[dict]
    static_analysis: dict           # {field: StaticAnalysisOutput dict}
    action_manifest: Optional[dict]

    # Synthesis
    state_map_path: Optional[str]
    state_map: Optional[dict]

    # Control
    phase: str
    errors: list[str]


def _default_state(cfg: dict, dry_run: bool = False, resume: bool = False) -> SessionState:
    mcp_cfg = cfg.get("mcp", {})
    return SessionState(
        session_id=cfg.get("session_id", "default"),
        game_exe=cfg.get("game_exe", ""),
        game_window_title=cfg.get("game_window_title", ""),
        module_name=cfg.get("module_name", ""),
        ghidra_binary_path=cfg.get("ghidra_binary_path", ""),
        scan_type=cfg.get("scan_type", "float"),
        seed_deltas=cfg.get("seed_deltas", []),
        log_file=cfg.get("log_file"),
        ce_server_path=mcp_cfg.get("ce_server_path", ""),
        ghidra_server_path=mcp_cfg.get("ghidra_server_path", ""),
        python_exe=mcp_cfg.get("python_exe", "python"),
        dry_run=dry_run,
        resume=resume,
        module_base=None,
        observed_deltas=[],
        scan_candidates={},
        pointer_chains={},
        raw_struct=None,
        static_analysis={},
        action_manifest=None,
        state_map_path=None,
        state_map=None,
        phase="attach",
        errors=[],
    )


def _checkpoint_path(state: SessionState) -> str:
    return f"session_checkpoint_{state.get('session_id', 'default')}.json"


# ---------------------------------------------------------------------------
# Node: attach_game
# ---------------------------------------------------------------------------

async def attach_game(state: SessionState) -> dict:
    updates: dict = {"phase": "vision_scout"}
    errors = list(state.get("errors", []))

    if state.get("dry_run"):
        print(f"[DRY RUN] CE attach: {state['game_exe']}")
        print(f"[DRY RUN] Ghidra open: {state['ghidra_binary_path']}")
        updates["module_base"] = 0x140000000
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    # CE attach + module base resolution
    # If game_exe is a .exe name (not a numeric PID), try to read exact PID from
    # tools/dummy_target.pid so we attach to the right instance.
    game_exe = state["game_exe"]
    if game_exe.lower().endswith(".exe"):
        pid_file = Path("tools/dummy_target.pid")
        if pid_file.exists():
            try:
                pid_from_file = pid_file.read_text().strip()
                if pid_from_file.isdigit():
                    game_exe = pid_from_file
                    print(f"[Attach] Using PID {game_exe} from tools/dummy_target.pid")
            except Exception:
                pass

    ce_ok = False
    try:
        async with CEClient(state["ce_server_path"], python_exe=state.get("python_exe", "python")) as ce:
            result = await ce.attach(game_exe)
            if not result.success:
                print(f"[Attach] WARNING: CE attach failed for '{state['game_exe']}' — continuing with defaults")
            else:
                ce_ok = True
                print(f"[Attach] CE: {result.process_name} (pid={result.process_id})")
                base = await get_module_base(ce, state["module_name"])
                if base:
                    updates["module_base"] = base
                    print(f"[Attach] {state['module_name']} @ 0x{base:X}")
                else:
                    # Log first few module names to help diagnose name mismatch
                    mods = await ce.list_modules()
                    names = [m.get("name", "?") for m in mods[:5]]
                    print(f"[Attach] WARNING: '{state['module_name']}' not in modules. First 5: {names}")
                    updates["module_base"] = 0x140000000
    except Exception as exc:
        msg = str(exc)
        if "TaskGroup" in msg or "cancel scope" in msg or type(exc).__name__ in ("ExceptionGroup", "BaseExceptionGroup"):
            # anyio cleanup noise — operations completed before __aexit__ failed; ignore
            pass
        elif "not reachable" in msg or "Bridge" in msg:
            print(f"[Attach] WARNING: CE pipe not reachable (Claude Desktop may hold the pipe).")
            print(f"[Attach]   Tip: run without Claude Desktop CE MCP active, or use --dry-run.")
        else:
            print(f"[Attach] WARNING: CE error: {exc}")
        # Preserve any module_base set before the exception; fall back to default otherwise
        updates.setdefault("module_base", 0x140000000)

    # Ghidra binary open (non-fatal — Ghidra may not have the binary loaded yet)
    try:
        async with GhidraClient(state["ghidra_server_path"], python_exe=state.get("python_exe", "python")) as gh:
            ok = await gh.load_binary(state["ghidra_binary_path"])
            print(f"[Attach] Ghidra: {'loaded' if ok else 'not found (static analysis will be skipped)'} {state['ghidra_binary_path']}")
    except Exception as exc:
        print(f"[Attach] WARNING: Ghidra not reachable: {exc} — static analysis will be skipped")

    updates["errors"] = errors
    # Never block on attach errors — downstream nodes handle missing data gracefully
    updates["phase"] = "vision_scout"
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


# ---------------------------------------------------------------------------
# Node: vision_scout
# ---------------------------------------------------------------------------

async def vision_scout(state: SessionState) -> dict:
    updates: dict = {"phase": "memory_scout"}

    if node_should_skip("vision_scout", state) and state.get("resume"):
        print("[Skip] vision_scout — checkpoint data present")
        return updates

    if state.get("dry_run"):
        updates["observed_deltas"] = [
            {"field": "hp",       "old_value": 100.0, "new_value": 85.0, "confidence": 0.95},
            {"field": "position_x", "old_value": 10.0, "new_value": 12.0, "confidence": 0.88},
        ]
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    window_title = state.get("game_window_title", "")
    seed_deltas = state.get("seed_deltas", [])

    if not window_title:
        # No GUI window — skip VLM.  Use seed_deltas from session config if provided.
        if seed_deltas:
            deltas = [dict(d) for d in seed_deltas]
            print(f"[VisionScout] No window configured — using {len(deltas)} seed_deltas from session config")
        else:
            print("[VisionScout] No window and no seed_deltas — vision step skipped; memory_scout will scan blindly")
            deltas = []
        updates["observed_deltas"] = deltas
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    vlm = VLMClient(window_title=window_title)
    print("[VisionScout] Capturing baseline screenshot...")
    baseline = vlm.capture_baseline()
    vlm.save_debug("debug_baseline.png")

    input("[VisionScout] Trigger a state change in-game, then press ENTER...")

    print("[VisionScout] Querying VLM for deltas...")
    obs = await vlm.observe_delta(baseline)
    deltas = [d.model_dump() for d in obs.deltas]
    print(f"[VisionScout] {len(deltas)} delta(s): {[d['field'] for d in deltas]}")

    if not deltas:
        # Fallback: ask user to describe the change manually
        print("[VisionScout] VLM returned no deltas. Manual entry:")
        field = input("  Field name (e.g. 'hp'): ").strip()
        old_v = float(input("  Old value: ").strip())
        new_v = float(input("  New value: ").strip())
        deltas = [{"field": field, "old_value": old_v, "new_value": new_v, "confidence": 1.0}]

    updates["observed_deltas"] = deltas
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


# ---------------------------------------------------------------------------
# Node: memory_scout
# ---------------------------------------------------------------------------

async def memory_scout(state: SessionState) -> dict:
    updates: dict = {"phase": "pointer_scout"}
    errors = list(state.get("errors", []))

    if node_should_skip("memory_scout", state) and state.get("resume"):
        print("[Skip] memory_scout — checkpoint data present")
        return updates

    if state.get("dry_run"):
        candidates = {}
        for delta in state.get("observed_deltas", []):
            candidates[delta["field"]] = ["0x7FF800A3F8C0", "0x7FF800B12340"]
        updates["scan_candidates"] = candidates
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    deltas = state.get("observed_deltas", [])
    if not deltas:
        errors.append("memory_scout: no observed_deltas to scan for")
        updates["errors"] = errors
        return updates

    try:
        candidates = await scan_all_fields_parallel(
            ce_server_path=state["ce_server_path"],
            session_id=state.get("session_id", "default"),
            observed_deltas=deltas,
            scan_type=state.get("scan_type", "float"),
            python_exe=state.get("python_exe", "python"),
            log_file=state.get("log_file"),
        )
        updates["scan_candidates"] = candidates
        print(f"[MemoryScout] Done: {list(candidates.keys())}")
    except Exception as exc:
        errors.append(f"memory_scout error: {exc}")

    updates["errors"] = errors
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


# ---------------------------------------------------------------------------
# Node: pointer_scout
# ---------------------------------------------------------------------------

async def pointer_scout(state: SessionState) -> dict:
    """
    Resolves stable pointer chains using two complementary strategies:
      A) Parse pointer path from Ghidra decompiled write function (preferred)
      B) If A fails, prompt user to run CE Pointer Scanner manually

    Strategy A works because decompiled code explicitly shows:
      actor->stats.hp = actor->stats.hp - damage;
    from which we extract the chain to `actor` and the `hp` offset within it.
    """
    updates: dict = {"phase": "struct_scout"}
    errors = list(state.get("errors", []))

    if node_should_skip("pointer_scout", state) and state.get("resume"):
        print("[Skip] pointer_scout — checkpoint data present")
        return updates

    if state.get("dry_run"):
        chains: dict = {}
        for field in state.get("scan_candidates", {}):
            chains[field] = {
                "base": f"{state.get('module_name', 'GameAssembly.dll')}+0x1A3F80",
                "offsets": [0x10, 0x48, 0x2C],
                "verified": True,
                "source": "dry_run",
            }
        updates["pointer_chains"] = chains
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    chains: dict = {}
    module_base = state.get("module_base") or 0
    scout = mk_pointer_scout()

    for field, addrs in state.get("scan_candidates", {}).items():
        if not addrs:
            continue
        live_addr = parse_addr(addrs[0])
        static_off = live_to_static(live_addr, module_base) if module_base else live_addr
        static_off_str = fmt_offset(static_off)

        # Strategy A: extract chain from Ghidra decompile
        chain_from_ghidra: Optional[dict] = None
        try:
            async with GhidraClient(state["ghidra_server_path"], python_exe=state.get("python_exe", "python")) as gh:
                xrefs = await gh.xrefs_to(static_off_str)
                write_xrefs = [r for r in xrefs if "WRITE" in r.ref_type.upper()] or xrefs
                if write_xrefs:
                    fn = await gh.decompile(write_xrefs[0].from_address)
                    # Ask Scout to extract pointer chain from pseudocode
                    prompt = (
                        f"Field: {field}\n"
                        f"Static offset in binary: {static_off_str}\n"
                        f"Module: {state.get('module_name')}, runtime base: {hex(module_base)}\n"
                        f"Decompiled write function:\n{fn.pseudocode[:2500]}\n\n"
                        "Extract the pointer chain to reach this field. "
                        "Return base as 'ModuleName+0xOFFSET' and offsets as integers."
                    )
                    out = await scout.ask(prompt, PointerChainOutput)
                    chain_from_ghidra = {
                        "base": out.base,
                        "offsets": out.offsets,
                        "verified": False,
                        "source": "ghidra_decompile",
                    }
                    print(f"[PointerScout] {field}: chain from Ghidra -> {out.base} + {out.offsets}")
        except Exception as exc:
            errors.append(f"PointerScout Ghidra strategy failed for {field}: {exc}")

        # Verify chain with live CE read
        if chain_from_ghidra and chain_from_ghidra.get("base") and chain_from_ghidra.get("offsets"):
            try:
                async with CEClient(state["ce_server_path"], python_exe=state.get("python_exe", "python")) as ce:
                    steps = await ce.read_chain(chain_from_ghidra["base"], chain_from_ghidra["offsets"])
                    if steps and steps[-1].value is not None:
                        chain_from_ghidra["verified"] = True
                        print(f"[PointerScout] {field}: chain verified, value={steps[-1].value}")
            except Exception as exc:
                errors.append(f"PointerScout CE verify failed for {field}: {exc}")
            chains[field] = chain_from_ghidra
        else:
            # Strategy B: Ghidra had no xrefs → heap/dynamic object.
            # Store the live address directly (dynamic_only — no static pointer chain).
            print(f"[PointerScout] {field}: no Ghidra xrefs — heap object, storing live addr directly")
            chains[field] = {
                "base": addrs[0],
                "offsets": [],
                "verified": False,
                "source": "dynamic",
                "dynamic_only": True,
            }

    updates["pointer_chains"] = chains
    updates["errors"] = errors
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


# ---------------------------------------------------------------------------
# Node: struct_scout
# ---------------------------------------------------------------------------

async def struct_scout(state: SessionState) -> dict:
    updates: dict = {"phase": "static_scout"}
    errors = list(state.get("errors", []))

    if node_should_skip("struct_scout", state) and state.get("resume"):
        print("[Skip] struct_scout — checkpoint data present")
        return updates

    if state.get("dry_run"):
        updates["raw_struct"] = {
            "class_name": "PlayerCharacter",
            "fields": [
                {"offset": 0x2C, "guessed_type": "float", "value": 85.0},
                {"offset": 0x30, "guessed_type": "float", "value": 100.0},
                {"offset": 0x34, "guessed_type": "float", "value": 60.0},
                {"offset": 0x50, "guessed_type": "float", "value": 10.0},
                {"offset": 0x54, "guessed_type": "float", "value": 12.0},
            ],
        }
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    scout = mk_struct_scout()
    all_addrs = [
        addrs[0]
        for addrs in state.get("scan_candidates", {}).values()
        if addrs
    ]
    if not all_addrs:
        errors.append("struct_scout: no candidate addresses")
        updates["errors"] = errors
        return updates

    # Use the first confirmed candidate address (most likely the object base)
    # Walk back to find the object head via pointer chain if available
    obj_addr = all_addrs[0]
    chains = state.get("pointer_chains", {})
    first_field = next(iter(chains), None)
    if first_field and chains[first_field].get("base") and chains[first_field].get("offsets"):
        # Try to read object address = resolve chain except last offset
        chain = chains[first_field]
        partial_offsets = chain["offsets"][:-1]
        if partial_offsets:
            try:
                async with CEClient(state["ce_server_path"], python_exe=state.get("python_exe", "python")) as ce:
                    steps = await ce.read_chain(chain["base"], partial_offsets)
                    if steps and steps[-1].address:
                        obj_addr = steps[-1].address
            except Exception:
                pass  # fall back to direct address

    try:
        async with CEClient(state["ce_server_path"], python_exe=state.get("python_exe", "python")) as ce:
            raw = await ce.dissect(obj_addr, size=512)
            class_name = await ce.rtti(obj_addr)

        fields_dump = [
            {"offset": f.offset, "guessed_type": f.guessed_type, "value": f.value}
            for f in raw.fields
        ]
        known_offsets = {
            field: chains[field]["offsets"][-1]
            for field in chains
            if chains[field].get("offsets")
        }

        prompt = (
            f"RTTI class: {class_name}\n"
            f"Object address: {obj_addr}\n"
            f"CE dissected fields ({len(fields_dump)} total): {json.dumps(fields_dump[:40])}\n"
            f"Known fields and their struct offsets: {json.dumps(known_offsets)}"
        )
        out = await scout.ask(prompt, StructAnalysisOutput)
        updates["raw_struct"] = {
            "class_name": out.class_name or class_name,
            "fields": out.adjacent_fields,
        }
        print(f"[StructScout] Class={out.class_name}, {len(out.adjacent_fields)} fields identified")
    except Exception as exc:
        errors.append(f"struct_scout error: {exc}")

    updates["errors"] = errors
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


# ---------------------------------------------------------------------------
# Node: static_scout
# ---------------------------------------------------------------------------

async def static_scout(state: SessionState) -> dict:
    """
    For each discovered field, decompiles its write functions in Ghidra and
    uses a Groq Scout to extract the full struct layout semantically.
    Uses StructBuilder to aggregate and deduplicate across multiple functions.
    """
    updates: dict = {"phase": "pattern_scout"}
    errors = list(state.get("errors", []))

    if node_should_skip("static_scout", state) and state.get("resume"):
        print("[Skip] static_scout — checkpoint data present")
        return updates

    if state.get("dry_run"):
        updates["static_analysis"] = {
            "hp": {
                "field": "hp",
                "static_offset": "0x2C",
                "write_functions": ["0x14023A400"],
                "struct_fields": [
                    {"name": "hp",       "offset": 0x2C, "type": "float", "semantic_role": "health"},
                    {"name": "hp_max",   "offset": 0x30, "type": "float", "semantic_role": "scalar"},
                    {"name": "stamina",  "offset": 0x34, "type": "float", "semantic_role": "scalar"},
                    {"name": "pos_x",    "offset": 0x50, "type": "float", "semantic_role": "coordinate_x"},
                    {"name": "pos_y",    "offset": 0x54, "type": "float", "semantic_role": "coordinate_y"},
                ],
                "class_name": "PlayerCharacter",
            }
        }
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    scout = mk_static_scout()
    module_base = state.get("module_base") or 0
    static_results: dict = {}

    # Build StructBuilder with CE dissect data first (low confidence baseline)
    builder = StructBuilder(
        class_name=state.get("raw_struct", {}).get("class_name") if state.get("raw_struct") else None
    )
    if state.get("raw_struct"):
        known_offsets = {
            f: chains.get(f, {}).get("offsets", [None])[-1]
            for f, chains in [(fld, state.get("pointer_chains", {})) for fld in state.get("scan_candidates", {})]
            if chains.get(f, {}).get("offsets")
        }
        builder.add_from_dissect(
            state["raw_struct"].get("fields", []),
            known_offsets={k: v for k, v in known_offsets.items() if v is not None},
        )

    # For each known field, run Ghidra static analysis
    for field, addrs in state.get("scan_candidates", {}).items():
        if not addrs:
            continue
        live_addr = parse_addr(addrs[0])
        static_off = live_to_static(live_addr, module_base) if module_base else live_addr
        # Heap objects have live_addr < module_base → negative offset → no static xrefs
        if static_off < 0:
            continue
        static_off_str = fmt_offset(static_off)

        try:
            async with GhidraClient(state["ghidra_server_path"], python_exe=state.get("python_exe", "python")) as gh:
                xrefs = await gh.xrefs_to(static_off_str)
                write_fns = [r.from_address for r in xrefs if "WRITE" in r.ref_type.upper()][:3]
                if not write_fns:
                    write_fns = [xrefs[0].from_address] if xrefs else []
                if not write_fns:
                    errors.append(f"static_scout: no xrefs for {field} @ {static_off_str}")
                    continue

                # Decompile up to 2 write functions and aggregate
                all_struct_fields: list[dict] = []
                for fn_addr in write_fns[:2]:
                    fn = await gh.decompile(fn_addr)
                    prompt = (
                        f"Field being analyzed: {field}\n"
                        f"Static offset in binary: {static_off_str}\n"
                        f"Module: {state.get('module_name')}, class hint: {state.get('raw_struct', {}).get('class_name') if state.get('raw_struct') else 'unknown'}\n"
                        f"Decompiled function '{fn.name}':\n{fn.pseudocode[:2500]}\n\n"
                        "Extract ALL struct fields accessed via the same base pointer. "
                        "Assign semantic roles: health, coordinate_x, coordinate_y, "
                        "coordinate_z, depth, time, threat, scalar, flag."
                    )
                    out = await scout.ask(prompt, StaticAnalysisOutput)
                    all_struct_fields.extend(out.struct_fields)

                # Dedup via StructBuilder
                builder.add_from_static_analysis(all_struct_fields)

                static_results[field] = {
                    "field": field,
                    "static_offset": static_off_str,
                    "write_functions": write_fns,
                    "struct_fields": all_struct_fields,
                    "class_name": state.get("raw_struct", {}).get("class_name") if state.get("raw_struct") else None,
                }
                print(f"[StaticScout] {field}: {len(all_struct_fields)} fields extracted")

            # Register struct in Ghidra
            final_fields = builder.finalize()
            if builder.class_name and final_fields:
                try:
                    async with GhidraClient(state["ghidra_server_path"], python_exe=state.get("python_exe", "python")) as gh:
                        await gh.create_struct(
                            name=builder.class_name,
                            fields=[{"name": f.name, "type": f.type_name, "offset": f.offset} for f in final_fields],
                        )
                        print(f"[StaticScout] Struct '{builder.class_name}' registered in Ghidra")
                except Exception:
                    pass  # non-fatal

        except Exception as exc:
            errors.append(f"static_scout error for {field}: {exc}")

    updates["static_analysis"] = static_results
    updates["errors"] = errors
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


# ---------------------------------------------------------------------------
# Node: pattern_scout
# ---------------------------------------------------------------------------

async def pattern_scout(state: SessionState) -> dict:
    updates: dict = {"phase": "synthesize"}
    errors = list(state.get("errors", []))

    if node_should_skip("pattern_scout", state) and state.get("resume"):
        print("[Skip] pattern_scout — checkpoint data present")
        return updates

    if state.get("dry_run"):
        updates["action_manifest"] = {
            "actions": [
                {"id": 0, "name": "MOVE_N",  "key_binding": "w",     "entry_point_addr": "0x14020A100"},
                {"id": 1, "name": "MOVE_S",  "key_binding": "s",     "entry_point_addr": "0x14020A120"},
                {"id": 2, "name": "MOVE_E",  "key_binding": "d",     "entry_point_addr": "0x14020A140"},
                {"id": 3, "name": "MOVE_W",  "key_binding": "a",     "entry_point_addr": "0x14020A160"},
                {"id": 4, "name": "ATTACK",  "key_binding": "space", "entry_point_addr": "0x14020A200"},
                {"id": 5, "name": "WAIT",    "key_binding": ".",     "entry_point_addr": None},
            ],
        }
        save_checkpoint({**state, **updates}, _checkpoint_path(state))
        return updates

    scout = mk_action_scout()

    try:
        async with GhidraClient(state["ghidra_server_path"], python_exe=state.get("python_exe", "python")) as gh:
            # Probe for input-related strings — these name the action dispatch code
            input_strs  = await gh.strings(filter_str="input",  limit=30)
            key_strs    = await gh.strings(filter_str="key",    limit=30)
            action_strs = await gh.strings(filter_str="action", limit=30)
            move_strs   = await gh.strings(filter_str="move",   limit=30)

        combined = (input_strs + key_strs + action_strs + move_strs)[:40]
        prompt = (
            f"Module: {state.get('module_name')}\n"
            f"Game: {state.get('game_exe')}\n"
            f"Input/action strings found in binary: {json.dumps(combined[:40])}\n\n"
            "Identify discrete player actions from these strings. "
            "Map each to a key binding and assign a short ALL_CAPS name. "
            "At minimum infer directional movement actions."
        )
        out = await scout.ask(prompt, ActionManifestOutput)
        updates["action_manifest"] = out.model_dump()
        print(f"[PatternScout] {len(out.actions)} actions discovered")
    except Exception as exc:
        errors.append(f"pattern_scout error: {exc}")
        # Fallback: ask user for actions
        print("[PatternScout] Falling back to manual action entry.")
        action_str = input("Enter action names as comma-separated list (e.g. MOVE_N,MOVE_S,ATTACK): ").strip()
        actions = [
            {"id": i, "name": a.strip(), "key_binding": None, "entry_point_addr": None}
            for i, a in enumerate(action_str.split(",")) if a.strip()
        ]
        updates["action_manifest"] = {"actions": actions}

    updates["errors"] = errors
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


# ---------------------------------------------------------------------------
# Node: synthesize -> state_map.json
# ---------------------------------------------------------------------------

async def synthesize(state: SessionState) -> dict:
    updates: dict = {"phase": "done"}
    errors = list(state.get("errors", []))

    if state.get("dry_run"):
        return _synthesize_dry_run(state, updates, errors)

    general = mk_general()

    # Aggregate struct fields from all static analysis results via StructBuilder
    builder = StructBuilder(
        class_name=state.get("raw_struct", {}).get("class_name") if state.get("raw_struct") else None
    )
    for field_data in state.get("static_analysis", {}).values():
        builder.add_from_static_analysis(field_data.get("struct_fields", []))

    chains = state.get("pointer_chains", {})
    action_manifest = state.get("action_manifest") or {}

    # Ask General to synthesize final state_map
    all_fields = [
        {"name": f.name, "offset": f.offset, "type": f.type_name, "semantic_role": f.semantic_role}
        for f in builder.finalize()
    ]
    prompt = (
        f"Game: {state.get('game_exe')}, module: {state.get('module_name')}\n"
        f"Class: {builder.class_name}\n\n"
        f"Discovered struct fields (merged from all analysis):\n{json.dumps(all_fields)}\n\n"
        f"Pointer chains (field -> base+offsets):\n{json.dumps(chains)}\n\n"
        f"Action manifest:\n{json.dumps(action_manifest.get('actions', []))}\n\n"
        "Produce a clean state_map.json. For each field: assign min/max bounds from "
        "domain knowledge or scan-observed ranges. Resolve any naming conflicts "
        "(prefer Ghidra decompile names). Drop fields with no clear semantic role."
    )

    try:
        judgment = await general.ask(prompt, SynthesisJudgment)
    except Exception as exc:
        errors.append(f"synthesis error: {exc}")
        # Fallback: build directly from StructBuilder without LLM
        judgment = None

    state_vars: dict[str, StateVariable] = {}

    if judgment and judgment.accepted_fields:
        for f in judgment.accepted_fields:
            _add_state_var(f, chains, state_vars)
    else:
        # Direct fallback from StructBuilder
        for f in builder.finalize():
            chain_data = chains.get(f.name)
            sm_chain = _build_sm_chain(chain_data) if chain_data else None
            try:
                role = SemanticRole(f.semantic_role)
            except ValueError:
                role = SemanticRole.SCALAR
            state_vars[f.name] = StateVariable(
                type=f.type_name, min=0.0, max=100.0,
                role=role,
                pointer_chain=sm_chain,
                struct_offset=f.offset,
                dynamic_only=(sm_chain is None),
                source="discovery",
            )

    if not state_vars:
        # Last-resort fallback: build directly from scan_candidates + pointer_chains
        scan_candidates = state.get("scan_candidates", {})
        if scan_candidates:
            print("[Synthesize] No struct data — building from scan_candidates directly")
            _ROLE_HINTS = {
                "health": SemanticRole.HEALTH, "hp": SemanticRole.HEALTH,
                "pos_x": SemanticRole.COORDINATE_X, "x": SemanticRole.COORDINATE_X,
                "pos_y": SemanticRole.COORDINATE_Y, "y": SemanticRole.COORDINATE_Y,
                "mana": SemanticRole.SCALAR, "stamina": SemanticRole.SCALAR,
                "turn": SemanticRole.TIME, "score": SemanticRole.SCALAR,
            }
            _delta_map = {d["field"]: d.get("new_value") for d in state.get("observed_deltas", [])}
            for fname, addrs in scan_candidates.items():
                if not addrs:
                    continue
                chain_data = chains.get(fname)
                sm_chain = _build_sm_chain(chain_data) if chain_data else None
                role = _ROLE_HINTS.get(fname.lower(), SemanticRole.SCALAR)
                state_vars[fname] = StateVariable(
                    type="float", min=0.0, max=100.0,
                    role=role,
                    pointer_chain=sm_chain,
                    struct_offset=None,
                    dynamic_only=(chain_data.get("dynamic_only", False) if chain_data else True),
                    source="scan_only",
                    initial_scan_value=_delta_map.get(fname),
                )
        if not state_vars:
            errors.append("synthesize: no state variables — pipeline produced no usable fields")
            updates["errors"] = errors
            return updates

    action_bindings = (
        judgment.action_bindings if (judgment and judgment.action_bindings) else
        [a.get("name", f"ACTION_{i}") for i, a in enumerate(action_manifest.get("actions", []))]
    )
    sm = StateMap(
        game_name=Path(state.get("game_exe", "unknown")).stem,
        engine_hint=state.get("engine_hint", "unknown"),
        binary=state.get("ghidra_binary_path", ""),
        module_name=state.get("module_name", ""),
        observation_dimensions=len(state_vars),
        state_variables=state_vars,
        actions=ActionManifest(count=len(action_bindings), bindings=action_bindings),
    )

    out_path = f"state_map_{sm.game_name}.json"
    sm.save(out_path)
    print(f"[Synthesize] Written: {out_path}  ({len(state_vars)} vars, {len(action_bindings)} actions)")

    updates["state_map_path"] = out_path
    updates["state_map"] = json.loads(sm.model_dump_json())
    updates["errors"] = errors
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


def _synthesize_dry_run(state: SessionState, updates: dict, errors: list) -> dict:
    chains = state.get("pointer_chains", {})
    action_manifest = state.get("action_manifest") or {}
    state_vars: dict = {}
    for field, chain_data in chains.items():
        sm_chain = _build_sm_chain(chain_data)
        state_vars[field] = StateVariable(
            type="float", min=0.0, max=100.0,
            role=SemanticRole.HEALTH if field == "hp" else SemanticRole.SCALAR,
            pointer_chain=sm_chain, source="discovery",
        )
    bindings = [a.get("name", f"ACTION_{i}") for i, a in enumerate(action_manifest.get("actions", []))]
    sm = StateMap(
        game_name=Path(state.get("game_exe", "unknown")).stem,
        binary=state.get("ghidra_binary_path", ""),
        module_name=state.get("module_name", ""),
        observation_dimensions=len(state_vars),
        state_variables=state_vars,
        actions=ActionManifest(count=len(bindings), bindings=bindings),
    )
    out_path = f"state_map_{sm.game_name}.json"
    sm.save(out_path)
    print(f"[DRY RUN] state_map written -> {out_path} ({len(state_vars)} vars, {len(bindings)} actions)")
    updates["state_map_path"] = out_path
    updates["state_map"] = json.loads(sm.model_dump_json())
    updates["errors"] = errors
    save_checkpoint({**state, **updates}, _checkpoint_path(state))
    return updates


def _build_sm_chain(chain_data: Optional[dict]) -> Optional[SMPointerChain]:
    if not chain_data or not chain_data.get("base"):
        return None
    return SMPointerChain(
        base=chain_data["base"],
        offsets=chain_data.get("offsets", []),
        verified=chain_data.get("verified", False),
    )


def _add_state_var(f: dict, chains: dict, out: dict) -> None:
    name = f.get("name", "")
    if not name:
        return
    chain_data = chains.get(name)
    sm_chain = _build_sm_chain(chain_data)
    role_str = f.get("role", "scalar")
    try:
        role = SemanticRole(role_str)
    except ValueError:
        role = SemanticRole.SCALAR
    out[name] = StateVariable(
        type="float",
        min=float(f.get("min", 0.0)),
        max=float(f.get("max", 100.0)),
        role=role,
        pointer_chain=sm_chain,
        struct_offset=f.get("struct_offset"),
        dynamic_only=(sm_chain is None and f.get("struct_offset") is None),
        source="discovery",
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def _route(state: SessionState) -> str:
    phase = state.get("phase", "error")
    if phase in ("error", "done"):
        return END
    return phase


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_graph():
    if not _LANGGRAPH_OK:
        raise ImportError("langgraph not installed. Run: pip install langgraph>=0.2.0")

    g = StateGraph(SessionState)
    g.add_node("attach",        attach_game)
    g.add_node("vision_scout",  vision_scout)
    g.add_node("memory_scout",  memory_scout)
    g.add_node("pointer_scout", pointer_scout)
    g.add_node("struct_scout",  struct_scout)
    g.add_node("static_scout",  static_scout)
    g.add_node("pattern_scout", pattern_scout)
    g.add_node("synthesize",    synthesize)

    g.set_entry_point("attach")

    for src, dst in [
        ("attach",        "vision_scout"),
        ("vision_scout",  "memory_scout"),
        ("memory_scout",  "pointer_scout"),
        ("pointer_scout", "struct_scout"),
        ("struct_scout",  "static_scout"),
        ("static_scout",  "pattern_scout"),
        ("pattern_scout", "synthesize"),
    ]:
        g.add_conditional_edges(src, _route, {dst: dst, END: END})

    g.add_edge("synthesize", END)
    return g.compile()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run(
    session_path: str,
    dry_run: bool = False,
    resume: bool = False,
) -> dict:
    from src.discovery.state_persistence import load_checkpoint

    with open(session_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if resume:
        session_id = cfg.get("session_id", "default")
        saved = load_checkpoint(f"session_checkpoint_{session_id}.json")
        state = saved or _default_state(cfg, dry_run=dry_run, resume=True)
        state["dry_run"] = dry_run
        state["resume"] = True
    else:
        state = _default_state(cfg, dry_run=dry_run)

    graph = build_graph()
    final = await graph.ainvoke(state)

    print("\n--- FINAL STATE ---")
    summary = {
        k: v for k, v in final.items()
        if k not in ("state_map",) and v not in (None, [], {})
    }
    print(json.dumps(summary, indent=2, default=str))

    if final.get("state_map_path"):
        print(f"\nstate_map.json -> {final['state_map_path']}")
    if final.get("errors"):
        print(f"Errors: {final['errors']}", file=sys.stderr)

    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge-Maker Orchestrator v2")
    parser.add_argument("--session", required=True, help="Path to session YAML")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume",  action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()
    asyncio.run(run(args.session, args.dry_run, args.resume))


if __name__ == "__main__":
    main()
