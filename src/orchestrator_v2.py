"""
Bridge-Maker Orchestrator v2 — Universal Grey-Box Discovery Pipeline.

Drives a hierarchical Scout/General swarm over CE MCP + Ghidra MCP to produce
state_map.json for any Windows game binary without game-specific code.

Phases (per master_roadmap_v2.md):
  Phase 1 — Infrastructure (this file is Phase 1.1)
  Phase 2 — Discovery pipeline (nodes below)
  Phase 3 — Gym env generation (invokes src/codegen/)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any, Optional, Sequence

import yaml
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# LangGraph imports
# ---------------------------------------------------------------------------
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    _LANGGRAPH_OK = True
except ImportError:
    _LANGGRAPH_OK = False
    # Minimal stub so the file is importable even without langgraph installed
    class StateGraph:  # type: ignore
        def __init__(self, *a, **kw): pass
        def add_node(self, *a, **kw): pass
        def add_edge(self, *a, **kw): pass
        def add_conditional_edges(self, *a, **kw): pass
        def set_entry_point(self, *a, **kw): pass
        def compile(self): return None
    END = "__end__"

from src.mcp.ce_client import CEClient
from src.mcp.ghidra_client import GhidraClient
from src.agents.scout_client import (
    GroqScout, memory_scout, pointer_scout, struct_scout,
    static_scout, action_scout, general_synthesizer,
    MemoryScanOutput, PointerChainOutput, StructAnalysisOutput,
    StaticAnalysisOutput, ActionManifestOutput, SynthesisJudgment,
)
from src.agents.vlm_client import VLMClient
from src.schema.state_map_schema import (
    StateMap, StateVariable, ActionManifest, ActionBinding,
    PointerChain as SMPointerChain, SemanticRole,
)


# ---------------------------------------------------------------------------
# Session State (LangGraph TypedDict)
# ---------------------------------------------------------------------------

from typing import TypedDict

class SessionState(TypedDict, total=False):
    # Config
    session_id: str
    game_exe: str
    game_window_title: str
    module_name: str
    ghidra_binary_path: str
    scan_type: str                  # "float" | "dword"
    ce_server_path: str
    ghidra_server_path: str
    dry_run: bool

    # Discovery results (populated by Scouts)
    module_base: Optional[int]
    observed_deltas: list[dict]     # [{field, old_value, new_value, confidence}]
    scan_candidates: dict           # {field: [address_str, ...]}
    pointer_chains: dict            # {field: {base, offsets, verified}}
    raw_struct: Optional[dict]      # {class_name, fields: [{offset, type, value}]}
    static_analysis: dict           # {field: StaticAnalysisOutput.dict()}
    action_manifest: Optional[dict] # ActionManifestOutput.dict()

    # Synthesis
    state_map_path: Optional[str]
    state_map: Optional[dict]

    # Control
    phase: str
    errors: list[str]


def _default_state(cfg: dict, dry_run: bool = False) -> SessionState:
    return SessionState(
        session_id=cfg.get("session_id", "default"),
        game_exe=cfg.get("game_exe", ""),
        game_window_title=cfg.get("game_window_title", ""),
        module_name=cfg.get("module_name", ""),
        ghidra_binary_path=cfg.get("ghidra_binary_path", ""),
        scan_type=cfg.get("scan_type", "float"),
        ce_server_path=cfg.get("mcp", {}).get("ce_server_path", ""),
        ghidra_server_path=cfg.get("mcp", {}).get("ghidra_server_path", ""),
        dry_run=dry_run,
        module_base=None,
        observed_deltas=[],
        scan_candidates={},
        pointer_chains={},
        raw_struct=None,
        static_analysis={},
        action_manifest=None,
        state_map_path=None,
        state_map=None,
        phase="init",
        errors=[],
    )


# ---------------------------------------------------------------------------
# Node: attach_game
# ---------------------------------------------------------------------------

async def attach_game(state: SessionState) -> dict:
    """
    Opens CE process attachment and Ghidra binary.
    In dry-run mode, mocks both without real MCP calls.
    """
    updates: dict = {"phase": "attach"}
    errors = list(state.get("errors", []))

    if state.get("dry_run"):
        print(f"[DRY RUN] Would attach CE to: {state['game_exe']}")
        print(f"[DRY RUN] Would open Ghidra binary: {state['ghidra_binary_path']}")
        updates["module_base"] = 0x140000000  # mock ASLR base
        updates["phase"] = "vision_scout"
        return updates

    # Real CE attach
    try:
        async with CEClient(state["ce_server_path"]) as ce:
            result = await ce.attach(state["game_exe"])
            if not result.success:
                errors.append(f"CE attach failed for {state['game_exe']}")
            else:
                print(f"[Attach] CE attached to {result.process_name} (pid={result.process_id})")
                # Resolve module base
                base = await ce.module_base(state["module_name"])
                if base:
                    updates["module_base"] = base
                    print(f"[Attach] Module base: {state['module_name']} @ 0x{base:X}")
    except Exception as exc:
        errors.append(f"CE attach error: {exc}")

    # Ghidra binary open
    try:
        async with GhidraClient(state["ghidra_server_path"]) as gh:
            ok = await gh.load_binary(state["ghidra_binary_path"])
            if ok:
                print(f"[Attach] Ghidra loaded: {state['ghidra_binary_path']}")
            else:
                errors.append(f"Ghidra load returned failure for {state['ghidra_binary_path']}")
    except Exception as exc:
        errors.append(f"Ghidra attach error: {exc}")

    updates["errors"] = errors
    updates["phase"] = "vision_scout" if not errors else "error"
    return updates


# ---------------------------------------------------------------------------
# Node: vision_scout
# ---------------------------------------------------------------------------

async def vision_scout(state: SessionState) -> dict:
    """
    Captures baseline screenshot, waits for user to trigger a state change,
    captures again, and asks VLM to identify observed deltas.
    """
    updates: dict = {"phase": "memory_scout"}

    if state.get("dry_run"):
        print("[DRY RUN] VisionScout: returning mock delta hp 100->85")
        updates["observed_deltas"] = [
            {"field": "hp", "old_value": 100.0, "new_value": 85.0, "confidence": 0.95}
        ]
        return updates

    vlm = VLMClient(window_title=state.get("game_window_title"))
    print("[VisionScout] Capturing baseline screenshot...")
    baseline = vlm.capture_baseline()
    vlm.save_debug("debug_baseline.png")

    input("[VisionScout] Trigger a state change in-game, then press ENTER...")

    print("[VisionScout] Capturing current screenshot and asking VLM...")
    observation = await vlm.observe_delta(baseline)

    deltas = [d.model_dump() for d in observation.deltas]
    print(f"[VisionScout] Detected {len(deltas)} delta(s): {[d['field'] for d in deltas]}")

    updates["observed_deltas"] = deltas
    return updates


# ---------------------------------------------------------------------------
# Node: memory_scout
# ---------------------------------------------------------------------------

async def memory_scout(state: SessionState) -> dict:
    """
    For each observed delta, runs CE scan rounds to find candidate addresses.
    """
    updates: dict = {"phase": "pointer_scout"}
    errors = list(state.get("errors", []))
    candidates: dict = dict(state.get("scan_candidates", {}))

    if state.get("dry_run"):
        for delta in state.get("observed_deltas", []):
            candidates[delta["field"]] = ["0x7FF800A3F8C0", "0x7FF800B12340"]
        updates["scan_candidates"] = candidates
        return updates

    scout = memory_scout()

    for delta in state.get("observed_deltas", []):
        field = delta["field"]
        new_val = str(delta["new_value"])
        scan_type = state.get("scan_type", "float")

        try:
            async with CEClient(state["ce_server_path"]) as ce:
                count = await ce.scan(new_val, scan_type=scan_type)
                print(f"[MemoryScout] {field}: first scan → {count} candidates")

                # prompt user for one more refinement round
                if count > 10:
                    input(f"[MemoryScout] Trigger another change to {field}, then ENTER...")
                    page = await ce.results(limit=5)
                    if page.results:
                        addrs = [r.address for r in page.results]
                        # Ask Scout to rank them
                        prompt = (
                            f"Field: {field}\nScan type: {scan_type}\n"
                            f"Observed new value: {new_val}\n"
                            f"CE candidates: {json.dumps(addrs)}"
                        )
                        out = await scout.ask(prompt, MemoryScanOutput)
                        candidates[field] = out.top_addresses or addrs[:5]
                    else:
                        candidates[field] = []
                else:
                    page = await ce.results(limit=5)
                    candidates[field] = [r.address for r in page.results]

                print(f"[MemoryScout] {field}: narrowed to {len(candidates[field])} candidates")
        except Exception as exc:
            errors.append(f"MemoryScout error for {field}: {exc}")

    updates["scan_candidates"] = candidates
    updates["errors"] = errors
    return updates


# ---------------------------------------------------------------------------
# Node: pointer_scout
# ---------------------------------------------------------------------------

async def pointer_scout_node(state: SessionState) -> dict:
    """
    For each candidate address, attempts to resolve a stable pointer chain
    that survives process restart.
    """
    updates: dict = {"phase": "struct_scout"}
    errors = list(state.get("errors", []))
    chains: dict = dict(state.get("pointer_chains", {}))

    if state.get("dry_run"):
        for field, addrs in state.get("scan_candidates", {}).items():
            chains[field] = {
                "base": f"{state.get('module_name', 'GameAssembly.dll')}+0x1A3F80",
                "offsets": [0x10, 0x48, 0x2C],
                "verified": True,
            }
        updates["pointer_chains"] = chains
        return updates

    scout = pointer_scout()
    module_base = state.get("module_base") or 0

    for field, addrs in state.get("scan_candidates", {}).items():
        if not addrs:
            continue
        addr = addrs[0]
        try:
            async with CEClient(state["ce_server_path"]) as ce:
                # Compute static offset relative to module base
                live_addr = int(addr, 16) if isinstance(addr, str) else addr
                static_off = live_addr - module_base if module_base else live_addr
                static_off_str = hex(static_off)

                # Read pointer chain from CE
                steps = await ce.read_chain(addr, [0x0, 0x10, 0x48])
                step_dump = [{"depth": s.depth, "address": s.address, "value": str(s.value)} for s in steps]

                prompt = (
                    f"Field: {field}\n"
                    f"Live address: {addr}\n"
                    f"Module: {state.get('module_name')}, base: {hex(module_base)}\n"
                    f"Static offset from module base: {static_off_str}\n"
                    f"Pointer chain steps: {json.dumps(step_dump)}"
                )
                out = await scout.ask(prompt, PointerChainOutput)
                chains[field] = {
                    "base": out.base,
                    "offsets": out.offsets,
                    "verified": out.verified,
                }
                print(f"[PointerScout] {field}: chain resolved — {out.base} + {out.offsets}")
        except Exception as exc:
            errors.append(f"PointerScout error for {field}: {exc}")

    updates["pointer_chains"] = chains
    updates["errors"] = errors
    return updates


# ---------------------------------------------------------------------------
# Node: struct_scout
# ---------------------------------------------------------------------------

async def struct_scout_node(state: SessionState) -> dict:
    """
    Takes the first confirmed address and dissects memory around it to find
    adjacent struct fields. Also extracts RTTI class name.
    """
    updates: dict = {"phase": "static_scout"}
    errors = list(state.get("errors", []))

    if state.get("dry_run"):
        updates["raw_struct"] = {
            "class_name": "PlayerCharacter",
            "fields": [
                {"offset": 0x2C, "guessed_type": "float", "value": 85.0},
                {"offset": 0x30, "guessed_type": "float", "value": 100.0},
                {"offset": 0x34, "guessed_type": "float", "value": 60.0},
            ],
        }
        return updates

    scout = struct_scout()
    all_addrs = [
        addrs[0]
        for addrs in state.get("scan_candidates", {}).values()
        if addrs
    ]
    if not all_addrs:
        updates["errors"] = errors + ["StructScout: no candidate addresses available"]
        return updates

    addr = all_addrs[0]
    try:
        async with CEClient(state["ce_server_path"]) as ce:
            raw = await ce.dissect(addr, size=512)
            class_name = await ce.rtti(addr)
            fields_dump = [
                {"offset": f.offset, "guessed_type": f.guessed_type, "value": f.value}
                for f in raw.fields
            ]

        # Ask Scout to interpret
        known_fields = state.get("scan_candidates", {})
        prompt = (
            f"RTTI class name: {class_name}\n"
            f"Base address: {addr}\n"
            f"Dissected fields: {json.dumps(fields_dump[:40])}\n"
            f"Known fields and their addresses: {json.dumps({k: v[0] if v else None for k, v in known_fields.items()})}"
        )
        out = await scout.ask(prompt, StructAnalysisOutput)
        updates["raw_struct"] = {
            "class_name": out.class_name or class_name,
            "fields": out.adjacent_fields,
        }
        print(f"[StructScout] Class: {out.class_name}, adjacent fields: {len(out.adjacent_fields)}")
    except Exception as exc:
        errors.append(f"StructScout error: {exc}")

    updates["errors"] = errors
    return updates


# ---------------------------------------------------------------------------
# Node: static_scout
# ---------------------------------------------------------------------------

async def static_scout_node(state: SessionState) -> dict:
    """
    For each field with a known static offset, finds write-xrefs in Ghidra,
    decompiles the write function, and extracts the full struct layout.
    """
    updates: dict = {"phase": "pattern_scout"}
    errors = list(state.get("errors", []))
    static_results: dict = dict(state.get("static_analysis", {}))

    if state.get("dry_run"):
        static_results["hp"] = {
            "field": "hp",
            "static_offset": "0x2C",
            "write_functions": ["0x14023A400"],
            "struct_fields": [
                {"name": "hp", "offset": 0x2C, "type": "float", "semantic_role": "health"},
                {"name": "hp_max", "offset": 0x30, "type": "float", "semantic_role": "scalar"},
                {"name": "stamina", "offset": 0x34, "type": "float", "semantic_role": "scalar"},
                {"name": "pos_x", "offset": 0x50, "type": "float", "semantic_role": "coordinate_x"},
                {"name": "pos_y", "offset": 0x54, "type": "float", "semantic_role": "coordinate_y"},
            ],
            "class_name": "PlayerCharacter",
        }
        updates["static_analysis"] = static_results
        return updates

    scout = static_scout()
    module_base = state.get("module_base") or 0

    for field, addrs in state.get("scan_candidates", {}).items():
        if not addrs:
            continue
        live_addr = int(addrs[0], 16) if isinstance(addrs[0], str) else addrs[0]
        static_offset = hex(live_addr - module_base) if module_base else hex(live_addr)

        try:
            async with GhidraClient(state["ghidra_server_path"]) as gh:
                xrefs = await gh.xrefs_to(static_offset)
                if not xrefs:
                    print(f"[StaticScout] No xrefs for {field} @ {static_offset}")
                    continue

                # Decompile first write function
                write_fns = [r.from_address for r in xrefs if "WRITE" in r.ref_type.upper()][:3]
                if not write_fns:
                    write_fns = [xrefs[0].from_address]

                decompiled = await gh.decompile(write_fns[0])
                print(f"[StaticScout] {field}: decompiled {decompiled.name}")

            prompt = (
                f"Field: {field}\n"
                f"Static offset in binary: {static_offset}\n"
                f"Class hint: {state.get('raw_struct', {}).get('class_name')}\n"
                f"Decompiled function ({decompiled.name}):\n{decompiled.pseudocode[:3000]}"
            )
            out = await scout.ask(prompt, StaticAnalysisOutput)
            static_results[field] = out.model_dump()
            print(f"[StaticScout] {field}: extracted {len(out.struct_fields)} struct fields")
        except Exception as exc:
            errors.append(f"StaticScout error for {field}: {exc}")

    updates["static_analysis"] = static_results
    updates["errors"] = errors
    return updates


# ---------------------------------------------------------------------------
# Node: pattern_scout
# ---------------------------------------------------------------------------

async def pattern_scout_node(state: SessionState) -> dict:
    """
    Discovers the action manifest: enumerates discrete player actions
    via Ghidra call graph analysis and AOB scanning of the input handler.
    """
    updates: dict = {"phase": "synthesize"}
    errors = list(state.get("errors", []))

    if state.get("dry_run"):
        updates["action_manifest"] = {
            "actions": [
                {"id": 0, "name": "MOVE_N", "key_binding": "w", "entry_point_addr": "0x14020A100"},
                {"id": 1, "name": "MOVE_S", "key_binding": "s", "entry_point_addr": "0x14020A120"},
                {"id": 2, "name": "MOVE_E", "key_binding": "d", "entry_point_addr": "0x14020A140"},
                {"id": 3, "name": "MOVE_W", "key_binding": "a", "entry_point_addr": "0x14020A160"},
                {"id": 4, "name": "ATTACK", "key_binding": "space", "entry_point_addr": "0x14020A200"},
                {"id": 5, "name": "WAIT", "key_binding": ".", "entry_point_addr": None},
            ],
        }
        return updates

    scout = action_scout()

    try:
        async with GhidraClient(state["ghidra_server_path"]) as gh:
            # Look for input-related strings to locate the handler
            input_strs = await gh.strings(filter_str="input", limit=50)
            key_strs = await gh.strings(filter_str="key", limit=50)
            action_strs = await gh.strings(filter_str="action", limit=50)

            combined = input_strs[:10] + key_strs[:10] + action_strs[:10]

        prompt = (
            f"Module: {state.get('module_name')}\n"
            f"Input/action-related strings found in binary: {json.dumps(combined[:30])}\n"
            "Identify discrete player actions from these strings and their likely key bindings. "
            "Infer action names from the string context."
        )
        out = await scout.ask(prompt, ActionManifestOutput)
        updates["action_manifest"] = out.model_dump()
        print(f"[PatternScout] Found {len(out.actions)} actions")
    except Exception as exc:
        errors.append(f"PatternScout error: {exc}")

    updates["errors"] = errors
    return updates


# ---------------------------------------------------------------------------
# Node: synthesize → state_map.json
# ---------------------------------------------------------------------------

async def synthesize(state: SessionState) -> dict:
    """
    General LLM synthesizes all Scout findings into a validated state_map.json.
    """
    updates: dict = {"phase": "done"}
    errors = list(state.get("errors", []))

    if state.get("dry_run"):
        chains = state.get("pointer_chains", {})
        action_manifest = state.get("action_manifest") or {}
        state_vars: dict = {}
        for field, chain_data in chains.items():
            sm_chain = SMPointerChain(
                base=chain_data.get("base", ""),
                offsets=chain_data.get("offsets", []),
                verified=chain_data.get("verified", False),
            )
            state_vars[field] = StateVariable(
                type="float", min=0.0, max=100.0,
                role=SemanticRole.HEALTH if field == "hp" else SemanticRole.SCALAR,
                pointer_chain=sm_chain, source="discovery",
            )
        action_bindings = [a.get("name", f"ACTION_{i}") for i, a in enumerate(action_manifest.get("actions", []))]
        sm = StateMap(
            game_name=Path(state.get("game_exe", "unknown")).stem,
            binary=state.get("ghidra_binary_path", ""),
            module_name=state.get("module_name", ""),
            observation_dimensions=len(state_vars),
            state_variables=state_vars,
            actions=ActionManifest(count=len(action_bindings), bindings=action_bindings),
        )
        out_path = f"state_map_{sm.game_name}.json"
        sm.save(out_path)
        print(f"[DRY RUN] state_map.json written -> {out_path} ({len(state_vars)} vars, {len(action_bindings)} actions)")
        updates["state_map_path"] = out_path
        updates["state_map"] = json.loads(sm.model_dump_json())
        updates["errors"] = errors
        return updates

    general = general_synthesizer()

    static = state.get("static_analysis", {})
    # Collect all struct fields across all analyzed fields (StaticScout is the richest source)
    all_struct_fields: list[dict] = []
    for field_data in static.values():
        all_struct_fields.extend(field_data.get("struct_fields", []))

    chains = state.get("pointer_chains", {})
    raw_struct = state.get("raw_struct") or {}
    action_manifest = state.get("action_manifest") or {}

    prompt = (
        f"Game: {state.get('game_exe')}\n"
        f"Module: {state.get('module_name')}\n"
        f"Class name: {raw_struct.get('class_name')}\n\n"
        f"Pointer chains (field → base+offsets): {json.dumps(chains)}\n\n"
        f"Struct fields from static analysis (may have duplicates/conflicts): {json.dumps(all_struct_fields)}\n\n"
        f"Action manifest: {json.dumps(action_manifest.get('actions', []))}\n\n"
        "Synthesize these into a clean state_map.json. "
        "Merge duplicate fields, resolve conflicts (prefer Ghidra names over heuristic names). "
        "Assign semantic roles and normalization bounds."
    )

    try:
        judgment = await general.ask(prompt, SynthesisJudgment)
    except Exception as exc:
        errors.append(f"Synthesis error: {exc}")
        updates["errors"] = errors
        return updates

    # Build StateMap from judgment
    state_vars: dict = {}
    for f in judgment.accepted_fields:
        chain_data = chains.get(f.get("name", ""), {})
        sm_chain = None
        if chain_data:
            sm_chain = SMPointerChain(
                base=chain_data.get("base", ""),
                offsets=chain_data.get("offsets", []),
                verified=chain_data.get("verified", False),
            )
        role_str = f.get("role", "scalar")
        try:
            role = SemanticRole(role_str)
        except ValueError:
            role = SemanticRole.SCALAR

        state_vars[f["name"]] = StateVariable(
            type="float",
            min=float(f.get("min", 0.0)),
            max=float(f.get("max", 100.0)),
            role=role,
            pointer_chain=sm_chain,
            struct_offset=f.get("struct_offset"),
            dynamic_only=(sm_chain is None),
            source="discovery",
        )

    if not state_vars:
        errors.append("Synthesis produced no accepted fields — check Scout outputs")
        updates["errors"] = errors
        return updates

    action_bindings = judgment.action_bindings or [
        a.get("name", f"ACTION_{a['id']}") for a in action_manifest.get("actions", [])
    ]
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
    print(f"[Synthesize] state_map.json written → {out_path}")
    print(f"[Synthesize] {len(state_vars)} state variables, {len(action_bindings)} actions")

    updates["state_map_path"] = out_path
    updates["state_map"] = json.loads(sm.model_dump_json())
    updates["errors"] = errors
    return updates


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def _route(state: SessionState) -> str:
    phase = state.get("phase", "error")
    if phase in ("error",):
        return END
    return phase if phase != "done" else END


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph():
    if not _LANGGRAPH_OK:
        raise ImportError("langgraph not installed. Run: pip install langgraph>=0.2.0")

    g = StateGraph(SessionState)
    g.add_node("attach", attach_game)
    g.add_node("vision_scout", vision_scout)
    g.add_node("memory_scout", memory_scout)
    g.add_node("pointer_scout", pointer_scout_node)
    g.add_node("struct_scout", struct_scout_node)
    g.add_node("static_scout", static_scout_node)
    g.add_node("pattern_scout", pattern_scout_node)
    g.add_node("synthesize", synthesize)

    g.set_entry_point("attach")

    g.add_conditional_edges("attach",        _route, {"vision_scout": "vision_scout", END: END})
    g.add_conditional_edges("vision_scout",  _route, {"memory_scout": "memory_scout", END: END})
    g.add_conditional_edges("memory_scout",  _route, {"pointer_scout": "pointer_scout", END: END})
    g.add_conditional_edges("pointer_scout", _route, {"struct_scout": "struct_scout", END: END})
    g.add_conditional_edges("struct_scout",  _route, {"static_scout": "static_scout", END: END})
    g.add_conditional_edges("static_scout",  _route, {"pattern_scout": "pattern_scout", END: END})
    g.add_conditional_edges("pattern_scout", _route, {"synthesize": "synthesize", END: END})
    g.add_edge("synthesize", END)

    return g.compile()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _run(session_path: str, dry_run: bool, phase_limit: Optional[str]) -> None:
    with open(session_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    state = _default_state(cfg, dry_run=dry_run)

    graph = build_graph()
    final = await graph.ainvoke(state)

    print("\n--- SESSION STATE ---")
    # Print a clean summary (omit heavy fields like pseudocode)
    summary = {
        k: v for k, v in final.items()
        if k not in ("state_map",) and v not in (None, [], {})
    }
    print(json.dumps(summary, indent=2, default=str))

    if final.get("state_map_path"):
        print(f"\nstate_map.json -> {final['state_map_path']}")
    if final.get("errors"):
        print(f"\nErrors: {final['errors']}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge-Maker Orchestrator v2")
    parser.add_argument("--session", required=True, help="Path to session YAML config")
    parser.add_argument("--dry-run", action="store_true", help="Mock MCP calls, test pipeline shape")
    parser.add_argument("--phase", help="Stop after this phase (e.g. memory_scout)")
    args = parser.parse_args()

    asyncio.run(_run(args.session, args.dry_run, args.phase))


if __name__ == "__main__":
    main()
