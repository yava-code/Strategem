# Phase 1 — Infrastructure & Swarm Scaffolding

**Files created:**
- `src/schema/state_map_schema.py` — Pydantic v2 models: `PointerChain`, `StateVariable`, `ActionManifest`, `StateMap` with validators
- `src/mcp/ce_client.py` — `CEClient` async context manager over CE MCP stdio; wraps `attach`, `scan`, `refine`, `results`, `pointer_rescan`, `read_chain`, `dissect`, `rtti`, `aob_module`, `module_base`
- `src/mcp/ghidra_client.py` — `GhidraClient` async context manager over Ghidra MCP stdio; wraps `load_binary`, `xrefs_to`, `decompile`, `function_at`, `byte_pattern`, `call_graph`, `strings`, `create_struct`, `struct_layout`, `search_functions`
- `src/agents/scout_client.py` — `GroqScout` base class with structured JSON responses via Pydantic; factory functions for all 6 Scout types + General synthesizer; output schemas: `MemoryScanOutput`, `PointerChainOutput`, `StructAnalysisOutput`, `StaticAnalysisOutput`, `ActionManifestOutput`, `VLMObservation`, `SynthesisJudgment`
- `src/agents/vlm_client.py` — `VLMClient` with `Screenshotter` (dxcam primary / PIL fallback / win32gui window resolution); Groq vision inference for state delta detection
- `src/agents/prompts/scout_base.txt` — shared Scout system prompt (JSON-only, domain naming)
- `src/orchestrator_v2.py` — LangGraph `StateGraph` with 8 nodes: `attach_game` → `vision_scout` → `memory_scout` → `pointer_scout` → `struct_scout` → `static_scout` → `pattern_scout` → `synthesize`; conditional edges via `_route`; `--dry-run` mode mocks all MCP/Groq calls
- `configs/session.yaml` — session config template (game_exe, module_name, ghidra_binary_path, scan_type, mcp server paths)
- `.env.example` — GROQ_API_KEY, GROQ_MODEL, GROQ_GENERAL_MODEL, GROQ_VLM_MODEL

**Requirements added:** `langgraph>=0.2.0`, `groq>=0.9.0`, `mcp>=1.5.0,<2.0.0`, `dxcam>=0.0.5`, `Pillow>=10.0.0`, `pywin32>=306`

**Verified:** `python -m src.orchestrator_v2 --session configs/session.yaml --dry-run` exits clean, prints full session state JSON with all 8 nodes traversed, writes `state_map_Game.json`.

**Phase 1 Done criterion met:** attach CE (mocked), open Ghidra (mocked), run VisionScout, print session state JSON.
