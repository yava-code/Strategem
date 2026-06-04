# Phase 2 — Discovery Pipeline

**Files created:**
- `src/discovery/__init__.py`
- `src/discovery/module_info.py` — `get_module_base(ce, name)` via `enum_modules` (fixes incorrect `get_symbol_address` usage); `live_to_static`, `fmt_offset`, `parse_addr` utilities
- `src/discovery/scan_session.py` — `FieldScanSession`: named persistent CE scans (state lives in CE between connections); `scan_all_fields_parallel`: `asyncio.gather` over all observed fields simultaneously; interactive loop until ≤5 candidates or 8 rounds
- `src/discovery/struct_builder.py` — `StructBuilder`: aggregates CE dissect (conf=0.55) + Ghidra static (conf=0.95) + Scout inference (conf=0.80); deduplicates by offset, higher confidence wins; `_infer_role` assigns semantic roles from field names; `to_state_map_format` converts to StateMap schema
- `src/discovery/state_persistence.py` — `save_checkpoint` / `load_checkpoint` JSON; `node_should_skip` checks populated state keys for resume
- `src/run_session.py` — multi-mode CLI: `--mode discover/generate/train/full`; delegates to orchestrator + codegen + training

**Files updated:**
- `src/mcp/ce_client.py` — fixed `module_base()` to use `enum_modules` (not `get_symbol_address`); added `persistent_create`, `persistent_first_scan`, `persistent_next_scan`, `persistent_results`, `persistent_destroy`
- `src/orchestrator_v2.py` — major rewrite:
  - Fixed naming collision: Scout factories imported as `mk_memory_scout`, `mk_pointer_scout`, etc.
  - All 8 node functions now use discovery modules
  - Checkpoint saved after every node
  - `--resume` flag: `node_should_skip` skips nodes whose output is already in state
  - `pointer_scout`: Strategy A = extract chain from Ghidra pseudocode (preferred); Strategy B = user-guided CE manual flow
  - `static_scout`: decompiles top 2 write functions per field, aggregates via `StructBuilder`, registers struct in Ghidra
  - `synthesize`: two paths — Groq General judgment (primary) and direct StructBuilder fallback (if Groq fails)
  - VisionScout fallback: manual value entry if VLM returns no deltas
  - PatternScout fallback: manual action list if Ghidra strings produce no signal

**Key design decisions:**
- Persistent scans: scan state lives in CE (not Python subprocess) so each CEClient connection is stateless
- Pointer chain discovery via Ghidra decompile (not CE pointer scanner GUI): decompiled pseudocode explicitly shows `actor->hp = ...` → extract chain
- StructBuilder confidence hierarchy: Ghidra static > Scout inference > CE dissect
- `--resume` skips any node with non-empty output in state → safe to re-run after interruption

**Verified:** dry-run traverses all 8 nodes; `--resume` skips 7/8 nodes on second run; checkpoint JSON written after every node; state_map_Game.json written with 2 fields + 6 actions.
