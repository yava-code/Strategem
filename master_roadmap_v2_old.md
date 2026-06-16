# The Bridge-Maker: Master Implementation Plan v2
## Universal Autonomous Black-Box/Grey-Box Game QA & RL Platform

**Architecture:** Hierarchical Agent Swarm (Scout/General) over CE MCP + Ghidra MCP + VLM.  
**Paradigm:** Attach to any game binary. Discover state via memory + vision. Generate Gym env. Deploy RL.  
**Constraint:** Zero game-specific code. Zero game modifications. Everything driven by `state_map.json`.

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PHASE 1: INFRASTRUCTURE                          │
│  LangGraph Orchestrator ←──── shared StateGraph ────► Scout Dispatcher  │
│  Groq Client (Scout pool)     CE MCP binding layer   Ghidra MCP binding │
│  VLM Client (dxcam + model)   .env / config loader   Session state store│
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │ state_map = {}
┌──────────────────────────────────────▼──────────────────────────────────┐
│                    PHASE 2: DISCOVERY PIPELINE                          │
│  VisionScout: screenshot → VLM delta  →  observed_value                 │
│  MemoryScout: CE scan_all → next_scan → candidate_addresses[]           │
│  PointerScout: pointer_rescan → read_pointer_chain → stable_chain       │
│  StructScout: dissect_structure → get_rtti_classname → raw_layout       │
│  StaticScout: Ghidra get_xrefs_to → decompile_function → struct_fields  │
│  PatternScout: analyze_call_graph → aob_scan → action_manifest          │
│  General LLM: synthesize all → state_map.json                           │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │ state_map.json
┌──────────────────────────────────────▼──────────────────────────────────┐
│                    PHASE 3: GYM ENVIRONMENT GENERATION                  │
│  StateMapParser → PydanticSpec → LLM Codegen → AST Validate → write     │
│  game_env_generated.py (pymem pointer reads, obs_space, action_space)   │
│  Smoke test: env.reset() → env.step() → frame validated                 │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │ gym.Env
┌──────────────────────────────────────▼──────────────────────────────────┐
│                       PHASE 4: RL INTEGRATION                           │
│  Ray/RLlib PPO + ICM Explorer    Oracle Layer (bug detection)           │
│  Multi-persona Groq swarm        Dashboard (SSE + glassmorphic UI)      │
│  bug_reports.jsonl               Reproducible repro (seed + action log) │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Infrastructure & Swarm Scaffolding

**Goal:** Build the orchestration skeleton. No game is attached yet. At the end of Phase 1, you can dispatch a Scout, have it call a CE/Ghidra MCP tool, and see the result land in shared state. Everything else builds on this.

### Task 1.1 — LangGraph Orchestrator Skeleton
- Create `src/orchestrator_v2.py`: a `StateGraph` with nodes for each Scout type and the General.
- State schema: `session_id`, `game_process`, `scan_candidates[]`, `pointer_chain{}`, `struct_layout{}`, `static_analysis{}`, `action_manifest{}`, `state_map_path`, `phase`, `errors[]`.
- Edges: VisionScout → MemoryScout → PointerScout → StructScout → (parallel) StaticScout + PatternScout → General.
- Conditional edge: General can re-dispatch any Scout if synthesis finds gaps.
- Entry: `attach_game` node (calls CE `open_process` + Ghidra `open_program`).

### Task 1.2 — Groq Scout Client
- Create `src/agents/scout_client.py`: thin async wrapper around Groq API.
- Model: configurable via `.env` (`GROQ_MODEL`, default `moonshotai/kimi-k2-instruct` or `llama-3.3-70b-versatile`).
- System prompt: loaded from `src/agents/prompts/scout_base.txt` (role, task, output format).
- Scouts return structured JSON responses only — no prose. Define output schemas with Pydantic.
- Rate-limit guard: exponential backoff on 429.

### Task 1.3 — VLM Client (Vision Scout Backend)
- Create `src/agents/vlm_client.py`.
- Screenshot capture: `dxcam` (primary, lowest latency) with `PIL.ImageGrab` fallback.
- Capture target: game window by title (found via CE `find_window` or win32gui).
- VLM inference: send screenshot to Groq vision-capable model (or local LLaVA via Ollama).
- Output: `{field: "hp", old_value: 75.0, new_value: 60.0, confidence: 0.92}`.
- Calibration mode: show bounding boxes on a saved screenshot so user can verify capture region.

### Task 1.4 — Cheat Engine MCP Binding Layer
- Create `src/mcp/ce_client.py`: typed wrapper functions over raw MCP tool calls.
- Expose: `attach(name)`, `scan(value, type)`, `refine(value, mode)`, `results(limit)`, `pointer_rescan(value)`, `read_chain(base, offsets)`, `dissect(addr, size)`, `rtti(addr)`, `aob_module(pattern, module)`.
- Each function validates its inputs, calls the MCP tool, and returns a typed dataclass.
- Session state: tracks current scan session and whether CE is attached.

### Task 1.5 — Ghidra MCP Binding Layer
- Create `src/mcp/ghidra_client.py`: typed wrapper over Ghidra MCP tools.
- Expose: `load_binary(path)`, `xrefs_to(addr)`, `decompile(addr)`, `byte_pattern(pat, mask)`, `call_graph(start, end)`, `strings(filter)`, `create_struct(name, fields)`, `struct_layout(name)`.
- Handles address normalization: accepts both static offset (int) and `"module+offset"` string notation.
- Prerequisite check: raises if no program is open in Ghidra.

### Task 1.6 — Session Config & .env Loader
- `configs/session.yaml`: `game_exe`, `game_window_title`, `ghidra_binary_path`, `scan_type` (float/dword), `module_name`.
- `src/config.py` updated to load session config + validate all required keys present.
- `.env.example`: `GROQ_API_KEY=`, `GROQ_MODEL=`, `VLM_PROVIDER=groq|ollama`, `OLLAMA_MODEL=`.

**Phase 1 Done When:** `python -m src.orchestrator_v2 --session configs/session.yaml --dry-run` attaches CE to a process, opens Ghidra binary, runs a single VisionScout mock, and prints the session state JSON.

---

## Phase 2 — Discovery Pipeline

**Goal:** Given a running game and a VLM-observed value change, produce a complete `state_map.json` containing all discoverable state fields, stable pointer chains, and a verified action manifest. No human input after initial attach.

### Task 2.1 — VisionScout: Observe → Delta
- VisionScout node in LangGraph: captures screenshot, calls VLM with prompt `"What game state values changed between these two screenshots? Return field name, old value, new value."`.
- Multi-round: takes baseline screenshot, triggers a game state change (user manually acts, or RL noise action), takes second screenshot, submits delta to VLM.
- Output → shared state: `observed_deltas: [{field, old_val, new_val, ui_region}]`.
- Parallel dispatch: multiple VisionScouts can observe different UI regions simultaneously (HP bar, mana bar, coordinates display, etc.).

### Task 2.2 — MemoryScout: Scan Rounds
- MemoryScout receives `observed_delta` from state: takes `new_val`, runs `scan_all`.
- Automatic refinement loop: for each subsequent VLM-observed change, calls `next_scan` with mode `exact` or `decreased`/`increased` based on delta direction.
- Terminates when: candidate count ≤ 5, or max 8 rounds reached (log warning).
- Dispatches multiple MemoryScouts in parallel for different `observed_deltas` (HP, position X, position Y simultaneously).
- Output → shared state: `scan_candidates: {field: [address_str, ...]}`.

### Task 2.3 — PointerScout: ASLR Defeat
- Receives `scan_candidates` from shared state.
- For each candidate address: triggers a game restart (user action), re-observes value via VLM, calls `pointer_rescan(new_value)`.
- Runs `read_pointer_chain(base_module_offset, [off1, off2, off3])` to verify the chain survives the restart.
- Selects the chain with the fewest offsets and highest stability score.
- Output → shared state: `pointer_chains: {field: {base, offsets[], verified: bool}}`.
- Fallback: if no stable chain found within 3 attempts, marks field as `dynamic_only` (runtime scan required each session).

### Task 2.4 — StructScout: Object Layout
- For each confirmed object address, calls `dissect_structure(addr, 512)`.
- Calls `get_rtti_classname(addr)` → extracts class name.
- Cross-references dissected fields with already-known fields from pointer_chains (by offset match).
- Output → shared state: `raw_struct: {class_name, fields: [{offset, type, candidate_name}]}`.
- Heuristic naming: offset of known HP field → scan ±64 bytes for adjacent fields of same type (likely hp_max, stamina, etc.).

### Task 2.5 — StaticScout: Ghidra Analysis (Core Intelligence Loop)
- Converts each live address to static offset: `static_offset = live_addr - module_base` (module_base from CE `enum_modules`).
- Calls `get_xrefs_to(static_offset)` → list of addresses that write to this field.
- For each write-xref: calls `decompile_function(xref_addr)` → pseudocode.
- Sends pseudocode to Groq Scout with prompt: `"Extract all struct fields accessed via the same pointer as offset 0xNN. Return field names, offsets, and types."`.
- Calls `create_struct(class_name, fields)` to register the layout in Ghidra.
- Verifies via `get_struct_layout(class_name)`.
- Output → shared state: `static_analysis: {class_name, struct_fields: [{name, offset, type, semantic_role}], write_functions: [addr, name]}`.

### Task 2.6 — PatternScout: Action Manifest
- Calls `list_strings(filter="key")`, `list_strings(filter="input")`, `list_strings(filter="action")` in Ghidra to locate input handler strings.
- From the string xrefs, identifies the input dispatch function address.
- Calls `analyze_call_graph(input_fn, game_update_fn)` to trace action → game state path.
- Runs `aob_scan_module(input_dispatch_pattern, module_name)` to locate stable byte signature.
- Groq Scout parses call graph output and identifies discrete action entry points.
- Output → shared state: `action_manifest: {actions: [{id, name, key_binding, entry_point_addr}], count: N}`.

### Task 2.7 — General: Synthesis → state_map.json
- Receives all shared state: pointer_chains, static_analysis, action_manifest.
- Resolves conflicts (e.g., CE struct field name vs. Ghidra decompiled name → prefer Ghidra).
- Assigns semantic roles: `health`, `coordinate_x`, `coordinate_y`, `depth`, `time`, `threat`, `scalar`.
- Determines normalization bounds: from decompiled code clamps, or from scan observed range.
- Writes `state_map.json` matching the existing schema (compatible with `src/connectors/dotnet_connector.py` CURATED_COQ_VARS format as reference).
- Schema fields: `game_name`, `engine_hint`, `binary`, `observation_dimensions`, `state_variables: {name: {type, min, max, role, pointer_chain, struct_offset, source}}`, `actions: {count, bindings[]}`.

**Phase 2 Done When:** Running `python -m src.orchestrator_v2 --session configs/session.yaml --phase discovery` produces a valid `state_map.json` for a test target (e.g., any simple open-source game or a synthetic test harness) with ≥3 discovered state fields and ≥2 verified actions.

---

## Phase 3 — Gym Environment Generation

**Goal:** Given `state_map.json`, auto-generate a production-ready `game_env_generated.py` that reads game memory in real-time via `pymem` pointer chains and exposes a standard `gymnasium.Env` interface. No human writes game-specific code.

### Task 3.1 — state_map.json Schema Validation
- `src/schema/state_map_schema.py`: Pydantic v2 models for the full state_map.json.
- `StateVariable`: `type`, `min`, `max`, `role`, `pointer_chain: {base: str, offsets: list[int]}`, `struct_offset: int | None`, `source: str`.
- `ActionManifest`: `count: int`, `bindings: list[str]`.
- `StateMap`: `game_name`, `engine_hint`, `state_variables: dict[str, StateVariable]`, `actions: ActionManifest`.
- Validator: rejects any map where pointer_chain is missing AND struct_offset is None (field is unresolvable).

### Task 3.2 — pymem Memory Reader Generator
- `src/codegen/mem_reader.py`: generates the `_read_state()` method body.
- For each field with a `pointer_chain`: emit `pm.read_float(pm.read_longlong(...) + offset)` chain.
- For direct struct fields (white-box mode future): emit single-offset read.
- Module base resolution: `pm.process_handle` + `pymem.process.module_from_name` → cached at env init.
- Output: Python source string for the reader method (not written to disk yet).

### Task 3.3 — Gym Observation/Action Space Generator
- `src/codegen/gym_spec.py`: generates `__init__`, `reset`, `step`, `observation_space`, `action_space` from `state_map.json`.
- Observation space: `gymnasium.spaces.Box(low, high, shape=(N,), dtype=np.float32)` with `low`/`high` arrays from `state_variables[*].min/max`.
- Normalization: min-max applied inside `_normalize_obs()`.
- Action space: `gymnasium.spaces.Discrete(N)` where N = `actions.count`.
- Action execution: dispatches via `pyautogui` or `win32api` key send by default; action binding source is `actions.bindings[]` from state_map.
- Reward: stub `0.0` — caller (RL engine or oracle layer) provides reward shaping.
- Output: Python source string for the full Gym class.

### Task 3.4 — LLM-Supervised Codegen + AST Validation
- `src/codegen/env_compiler.py`: assembles the full `game_env_generated.py` from Task 3.2 + 3.3 outputs.
- Passes the assembled source to the General LLM for a single review round: `"Review this Gym env for correctness against the state_map. Flag any type mismatches, missing fields, or pointer chain errors."`.
- Applies LLM corrections if flagged.
- Runs `ast.parse()` gate — rejects if syntax error.
- Runs `importlib.util.spec_from_loader` to confirm the module loads without import errors.
- Writes to `src/game_env_generated.py` only after both gates pass.

### Task 3.5 — Smoke Test
- `tests/test_generated_env.py`: instantiates the generated env, calls `reset()`, calls `step(0)` ten times.
- Asserts: obs shape matches `observation_space.shape`, no pymem exceptions, `done` is bool.
- Does NOT require the game to be in a specific state — just confirms the plumbing works.
- If pymem read fails (game not running or wrong pointer): test prints diagnostic (field name, pointer chain, address read at each level) and exits cleanly.

**Phase 3 Done When:** `pytest tests/test_generated_env.py` passes with a game running in background, and the generated env file contains no hardcoded game names, addresses, or field names (all driven from state_map.json).

---

## Phase 4 — RL Integration & Bug Hunting

**Goal:** Deploy the generated Gym env under Ray/RLlib + ICM. Add an oracle layer that classifies game states as bugs. Deploy a multi-persona Groq swarm for action selection at decision points. Stream results to dashboard.

### Task 4.1 — Ray/RLlib + ICM Explorer
- Update `src/train_rllib.py` to register `game_env_generated.GameEnvGenerated` as `bridge_maker_universal`.
- PPO config: `exploration_config = {type: "Curiosity", ...}` (reuse existing `configs/rllib_curiosity.yaml` template).
- ICM: Feature encoder (3-layer MLP on obs), forward model (predicts next feature), inverse model (predicts action from feature pair). Loss per Pathak et al.
- Multi-worker rollout: `num_rollout_workers = 4` default, configurable.
- Checkpoint: save every 50 iterations to `checkpoints/{game_name}/`.

### Task 4.2 — Oracle Layer (Bug Detection)
- `src/oracles.py`: stateless oracle functions called after each `env.step()`.
- `EXCEPTION_ORACLE`: wraps the env step in try/except — any unhandled exception during a turn is a confirmed bug.
- `INVARIANT_ORACLE`: checks invariants from state_map semantic roles — `hp < 0`, `coordinate_x > map_bounds`, `hp > hp_max`.
- `SOFTLOCK_ORACLE`: N consecutive steps with zero state change and non-terminal `done`.
- `STUCK_ORACLE`: same observation vector for M steps (possible softlock or collision).
- Each oracle emits: `{oracle_type, step, obs_snapshot, action_sequence[-20:], seed, detail}` → appended to `bug_reports.jsonl`.

### Task 4.3 — Multi-Persona Groq Action Swarm (Phase 2 feature, scaffold now)
- `src/agents/action_swarm.py`: called when RL policy needs a decision at high-value states (optional override mode).
- Three Groq Scout personas dispatched in parallel: `aggressive` (max risk), `cautious` (min hp loss), `completionist` (maximize novel states).
- Each receives: `{state_text, legal_actions[], recent_history[-5]}`.
- General votes among the three responses or picks the most novel action.
- Integrates with Ray as a custom exploration plugin (replaces ICM at flagged states).
- API key: `GROQ_API_KEY` from env.

### Task 4.4 — Dashboard (Extend Existing)
- Update `src/dashboard.py` to add a **Bug Feed** panel: SSE stream from `bug_reports.jsonl` tail.
- Bug card: oracle type badge, step number, obs snapshot table, `[Copy Repro Seed]` button.
- Explorer panel: heatmap of visited `(x, y)` cells from state_map coordinate fields.
- Swarm panel: per-worker reward/curiosity curves (reuse existing `/api/swarm` endpoint).
- Session panel: game name, binary path, state_map field count, action count — loaded from `state_map.json`.
- Zero new dependencies — all SSE, native JS, CSS variables.

### Task 4.5 — Session Runner CLI
- `src/run_session.py`: single entry point for the full pipeline.
- `--mode discover`: runs Phase 1-2, produces `state_map.json`, exits.
- `--mode generate`: runs Phase 3 from existing `state_map.json`, exits.
- `--mode train`: runs Phase 4 using existing `game_env_generated.py`.
- `--mode full`: runs all phases in sequence.
- `--session configs/session.yaml`: required for all modes.
- `--dashboard`: starts dashboard server alongside training.

**Phase 4 Done When:** `python -m src.run_session --mode full --session configs/session.yaml --dashboard` runs end-to-end on a test binary (or `tools/mock_coq_server.py` as a stand-in), produces at least one oracle hit in `bug_reports.jsonl`, and renders it on the dashboard.

---

## Retained Artifacts (Still Valid, Not Rewritten)

| File | Status | Notes |
|---|---|---|
| `src/reward_generator.py` | **Keep** | ICM math is correct; reuse in Phase 4 |
| `src/dashboard.py` | **Keep + Extend** | Phase 4.4 adds panels |
| `src/config.py` | **Keep + Extend** | Add session.yaml support |
| `src/connectors/` | **Archive** | Valid reference for state_map schema; not in live pipeline |
| `tools/mock_coq_server.py` | **Keep** | Useful synthetic test target for Phases 3-4 |
| `mods/CoQ_QA_Bridge/` | **Archive** | CoQ-specific, out of scope; kept for reference |
| `src/swarm.py` | **Deprecate** | Socket-control model retired; replaced by Phase 4.3 |
| `src/live_game_env.py` | **Deprecate** | Replaced by Phase 3 generated env |
| `master_roadmap.md` | **Archive** | Superseded by this document |

---

## Open Risks & Research Items

| Risk | Mitigation |
|---|---|
| Anti-cheat (EAC, BattleEye) blocks CE kernel driver | Platform targets single-player / dev builds; document clearly |
| VLM delta detection unreliable on fast games | Add frame delta threshold; fallback to pixel-diff heuristic |
| Pointer chain breaks across game patches | Re-run PointerScout on patch; state_map versioned by hash |
| Groq rate limits slow multi-Scout parallelism | Persistent scan sessions reduce round-trips; Scout result caching |
| Ghidra analysis on large binaries (>100 MB) is slow | Run `open_program(auto_analyze=false)` + targeted analysis only |
| Action dispatch via pyautogui unreliable in background window | Use `win32api.SendMessage` with WM_KEYDOWN; test per-game |

---

_This roadmap supersedes `master_roadmap.md`. Implementation begins after explicit approval._
