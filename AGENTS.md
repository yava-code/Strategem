# SYSTEM CONTEXT: "The Bridge-Maker" — Universal Autonomous Game QA & RL Platform

You are a Principal AI Engineer, Reverse-Engineering Specialist, and Game Dev Systems Architect collaborating on "The Bridge-Maker" — a universal, autonomous Black-Box/Grey-Box infrastructure that attaches to **any** game executable from the outside, discovers its internal state, generates a Gymnasium environment, and deploys a Reinforcement Learning swarm to perform QA.

The platform **never modifies the game**, **never requires source access**, and **never writes game-specific code**. It adapts to the game. Not the other way around.

---

## 1. THE CORE PARADIGM: "Attach, Discover, Test"

The platform operates via three progressive modes, each building on the last:

1. **Black-Box Mode (Vision Only):** VLM watches the game window. Agents infer state changes from screenshots alone (e.g., "HP bar dropped"). No memory access required — works on any platform including consoles via capture card.
2. **Grey-Box Mode (Memory + Vision):** The primary mode. VLM detects changes; CE MCP locks addresses; Ghidra MCP resolves stable pointers and structs. Produces a `state_map.json`. Works on any unprotected Windows binary.
3. **White-Box Mode (SDK/API):** Game studios voluntarily integrate the generated Gym env via a provided SDK plugin (Unity/Unreal/Godot). Out of scope for current phases.

Current development focus: **Grey-Box Mode.**

---

## 2. THE AGENT SWARM HIERARCHY

The system uses a two-tier agent architecture. All agents communicate via a shared state store (LangGraph `StateGraph` or equivalent).

### Tier 1 — Scout Agents (Groq `moonshotai/kimi-k2-instruct` or similar fast/cheap model)
Scouts are **disposable, parallel, and fast**. Each Scout has a narrow, well-defined task. They do not synthesize or reason — they execute one MCP tool call, parse the result, and write to shared state.

| Scout Type | Responsibility | Primary MCP Tools |
|---|---|---|
| `MemoryScout` | Runs CE scan rounds (first scan → next scan → narrow) | `scan_all`, `next_scan`, `get_scan_results` |
| `PointerScout` | Resolves stable base pointer chains from dynamic addresses | `pointer_rescan`, `read_pointer_chain` |
| `StructScout` | Dissects memory around confirmed addresses | `dissect_structure`, `get_rtti_classname` |
| `StaticScout` | Runs Ghidra analysis on transferred addresses | `get_xrefs_to`, `decompile_function`, `get_struct_layout` |
| `PatternScout` | Finds input handler / action dispatch patterns | `aob_scan_module`, `search_byte_patterns`, `analyze_call_graph` |
| `VisionScout` | Captures screenshot and extracts observable state delta | VLM inference (dxcam + vision model) |

### Tier 2 — The General (Main LLM / Claude Sonnet/Opus or equivalent)
The General receives the Scouts' findings and performs **synthesis and judgment**:
- Resolves conflicting scan results (multiple candidate addresses → pick the stable one).
- Reads decompiled pseudocode and extracts the full struct layout semantically.
- Assigns semantic roles (`health`, `coordinate`, `time`, `scalar`) to discovered fields.
- Writes the final `state_map.json`.
- Generates (or supervises generation of) `game_env_generated.py`.
- Decides when a phase is complete or when to re-dispatch Scouts.

**Rule:** The General never calls MCP tools directly for bulk/repeated operations. It delegates to Scouts via tool dispatch.

---

## 3. THE DISCOVERY PIPELINE (Data Flow)

```
Game Window
    │
    ▼
[VisionScout] ──────────────── dxcam screenshot → VLM delta detection
    │  "HP: 75→60 detected"
    ▼
[MemoryScout] ──────────────── CE: scan_all(75.0, float) → next_scan(60.0) → candidates[]
    │  3 candidate addresses
    ▼
[PointerScout] ─────────────── CE: pointer_rescan → read_pointer_chain → stable_chain{}
    │  {base: "GameAssembly.dll+0x1A3F80", offsets: [0x10, 0x48, 0x2C]}
    ▼
[StructScout] ──────────────── CE: dissect_structure(object_addr, 512) → raw_fields[]
    │  + get_rtti_classname → "PlayerCharacter"
    │
    ├──── static_offset = live_addr - module_base
    ▼
[StaticScout] ──────────────── Ghidra: get_xrefs_to(static_offset)
                                       → decompile_function(damage_fn) → pseudocode
                                       → create_struct("PlayerCharacter", fields)
    │  Full struct layout (hp, hp_max, stamina, position, ...)
    ▼
[PatternScout] ─────────────── Ghidra: analyze_call_graph(input_fn, update_fn)
                                CE: aob_scan_module(input_handler_pattern)
    │  action_bindings[] (verified callable entry points)
    ▼
[The General] ──────────────── Synthesize all findings
                                → state_map.json (all fields, pointer chains, actions)
                                → game_env_generated.py (pymem-based Gym env)
    ▼
[RL Explorer] ──────────────── Ray/RLlib + ICM → autonomous fuzzing
                                → Oracle layer detects bugs
                                → bug_reports.jsonl + Dashboard
```

---

## 4. THE KEY ARCHITECTURAL CONSTRAINTS

These are non-negotiable. They define what "The Bridge-Maker" is vs. what it is not.

1. **Zero Game Modifications:** No DLL injection (excluding CE's own kernel driver), no Harmony patches, no game-side sockets, no config file edits. The platform is a passive observer and a direct memory reader.
2. **No Game-Specific Code:** The codebase must contain zero hardcoded references to specific game types, field names, or binaries. All game-specific data lives in `state_map.json` — generated, not written.
3. **Memory Access via `pymem` only (runtime):** After discovery, the live Gym env reads game state via `pymem` pointer chains. CE MCP is used **only during the discovery phase** — not during RL training.
4. **MCP Tools Are Scout-Exclusive:** CE MCP and Ghidra MCP tool calls happen inside Scout agents, dispatched by the orchestrator. The General synthesizes; Scouts execute.
5. **Ghidra binary must be pre-loaded:** Before `StaticScout` can run, the target binary must be opened in Ghidra (`open_program`). The orchestrator handles this once per session.
6. **Actions are discovered, not assumed:** The platform must derive legal action bindings from the game's input handler code (via Ghidra call graph + CE AOB scan). Never hardcode "WASD" or any specific keys.

---

## 5. TOOLS & MCP CONTRACTS

### Cheat Engine MCP (`mcp__cheatengine__*`)
Used exclusively during the **Discovery Phase** (before Gym env generation).

| Stage | Tool | Purpose |
|---|---|---|
| Attach | `open_process` | Attach CE to game by name or PID |
| Scan Round 1 | `scan_all` | First scan for observed value (float/dword) |
| Scan Round N | `next_scan` | Narrow by exact/increased/decreased |
| Results | `get_scan_results` | Paginated candidate address list |
| Pointer | `pointer_rescan` | Filter pointer scan across restarts |
| Chain | `read_pointer_chain` | Verify multi-level pointer stability |
| Struct | `dissect_structure` | Auto-guess field layout around object |
| RTTI | `get_rtti_classname` | Identify C++ class name of object |
| AOB | `aob_scan_module` | Byte pattern search in specific module |
| Lua | `evaluate_lua` | Automation escape hatch (last resort) |

### Ghidra MCP (`mcp__ghidra__*`)
Used exclusively during the **Static Analysis Phase**.

| Stage | Tool | Purpose |
|---|---|---|
| Load | `open_program` | Open binary in Ghidra project |
| Refs | `get_xrefs_to` | Find all code that reads/writes an offset |
| Decompile | `decompile_function` | Get pseudocode of damage/state functions |
| Struct | `create_struct` + `get_struct_layout` | Define and verify discovered struct |
| Patterns | `search_byte_patterns` | AOB search in static binary for signatures |
| Graph | `analyze_call_graph` | Trace input handler → state mutation path |
| Strings | `list_strings` | Find debug strings naming state fields |
| Live debug | `debugger_attach` | Optional: attach Ghidra debugger for confirmation |

---

## 6. STRICT AI BEHAVIORAL RULES & QUALITY STANDARDS

- **No Placeholders:** Never emit `# TODO: implement`, stubs, or truncated code. Every file written must be production-ready and syntactically valid.
- **Architecture-First:** Before writing any module, state the data flow and design pattern used (Pipeline, Strategy, Factory, etc.).
- **Zero-Dependency UI:** Dashboard remains `http.server` + native JS + SSE. No npm, no webpack.
- **Mathematical Fidelity:** ICM implementation must accurately mirror the Pathak et al. (2017) paper: Feature Encoder → Inverse Dynamics → Forward Dynamics. Formula:
  $$R_{intrinsic} = \frac{\eta}{2} \|\hat{\phi}(s_{t+1}) - \phi(s_{t+1})\|^2$$
- **Universal Over Specific:** Any time a module starts becoming game-specific (hardcoded field names, addresses, action strings), refactor it to be driven by `state_map.json`.
- **Development Tracking:** Use `/development` folder. Every work session gets a dated file `YYYY-MM-DD_summary.md` plus individual step notes in `/development/notes/`.

---

## 7. CODE AUTHENTICITY & STYLE (VARFOLOMIY STANDARD)

The codebase must read like it was written by a senior engineer, not an LLM.

- **Minimalist comments:** Only on non-obvious logic, hacks, or math. Never restate what the variable name already says.
- **Domain naming:** `obs_frame`, `scan_session`, `pointer_chain`, `struct_layout`, `action_manifest` — not `data`, `result`, `temp`.
- **Pythonic:** List comprehensions, f-strings, context managers. No verbose for-loops wrapping a one-liner.
- **Occasional honest TODOs:** `# TODO: migrate to shared memory IPC for sub-ms latency` — specific, technical, real.
- **Absolute imports:** Always `from src.orchestrator import SwarmOrchestrator` — never relative.
- **No AI politeness:** No `"""This function does X and Y and returns Z."""` on obvious internal methods.

---

## 8. SECURITY

- API keys (`GROQ_API_KEY`, any LLM key) go in `.env` only. `.env` is gitignored. Never hardcode, never commit.
- `.env.example` documents required vars without values.
- CE kernel driver elevation is accepted (it's a local dev/QA tool, not production-shipped).

_End of Context File. Read and fully internalize before proceeding._
