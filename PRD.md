# PRD — The Bridge-Maker: Live Roguelike QA Swarm

**Status:** MVP implemented (demo target: Caves of Qud)
**Owner:** Varfolomiy
**Last updated:** 2026-06-03

---

## 1. Problem

Indie roguelike developers have no affordable, automated way to hunt softlocks,
economy exploits, numeric/crash bugs, and unreachable content. Manual playtesting
is slow, shallow, and doesn't scale across builds. Existing RL tooling
(ML-Agents, RLlib) assumes you instrument your own engine — useless against a game
you only have as a build, and pointless for a "bot that presses keys without
knowing the game's state."

## 2. Product

Point The Bridge-Maker at a game. It:
1. **Detects the engine** and picks a connector (the *ladder*).
2. **Discovers the state schema** (`state_map.json`) — for Caves of Qud, by reading
   the real `Assembly-CSharp.dll` type surface; for native games, via Ghidra-MCP;
   for LÖVE/Lua, by reading bundled Lua; vision as universal fallback.
3. **Wraps the game as a Gymnasium env** over a live socket transport.
4. **Runs a QA swarm** — several curiosity-driven RL testers, each with a different
   reward profile (exploit-hunter, speedrunner, chaos) — that explore and log
   anomalies without being told the rules.
5. **Reports** faults on a live glassmorphic dashboard: per-tester metrics, a
   cell-coverage heatmap, and an anomaly/exploit stream; plus an aggregate
   `swarm_report.json`.

Curiosity (ICM) is what makes the tester *purposeful* without an API: maximizing
novel-state coverage is, operationally, automated bug hunting.

## 3. Users & value
- **Indie dev (own game):** drop in a tiny bridge mod → overnight QA swarm.
- **Researcher/QA lead:** point at a build → coverage + repro-able fault log.

## 4. Why Caves of Qud for the demo
- True traditional roguelike (grid, turns, HP, depth) → matches the genre and
  reuses the existing spatial QA machinery (heatmaps, OOB/collision anomalies).
- Unity **Mono** → `Assembly-CSharp.dll` decompiles to near-source: the honest,
  working version of "agents read the code to find the state."
- First-class **Harmony modding** → a robust two-way state/action bridge.

## 5. Architecture (connector ladder)
```
IntegrationOrchestrator.detect(target)
  Unity/Mono  -> DotNetConnector  (+ CoQ QA Bridge mod)      [active]
  LÖVE/Lua    -> LuaBridgeConnector (Lovely mod)             [scaffold]
  Native C/C++-> GhidraConnector  (Ghidra-MCP)               [scaffold]
  fallback    -> VisionConnector  (screen capture + VLM)     [scaffold]
        -> state_map.json + GameTransport (length-prefixed JSON over TCP)
        -> LiveGameEnv (reuses reward_generator + ICM + logger)
        -> QASwarm (N testers × reward profiles)  -> dashboard + swarm_report.json
```

## 6. MVP scope
- **Built & verified now (headless via protocol-accurate mock):** connector
  framework, socket transport, `DotNetConnector` (curated CoQ schema + optional
  pythonnet reflection), orchestrator, `LiveGameEnv`, `QASwarm`, multi-agent
  dashboard, `tools/mock_coq_server.py`, `configs/coq_qa.yaml`.
- **Complete source, user-enabled:** `mods/CoQ_QA_Bridge` (Harmony mod).
- **Scaffolds (next milestones, real interfaces):** Ghidra, Lua, Vision rungs.

## 7. Success criteria (MVP) — met
1. Orchestrator detects CoQ as `unity-mono` and writes a 9-dim `state_map.json`. ✅
2. Swarm trains over the live socket protocol (mock today, mod later). ✅
3. Multiple reward profiles surface **distinct fault classes**
   (`HAZARD_DAMAGE`, `CRASH_NUMERIC`, `SOFTLOCK_SUSPECTED`). ✅
4. Per-tester heatmaps + anomaly reports + aggregate `swarm_report.json`. ✅
5. Real-game path is "enable the mod, `--transport live`" — no Python change. ✅

## 8. Non-goals (MVP)
- Winning/finishing the game; perfect cross-engine generality;
  anti-cheat evasion; dumping whole binaries into an LLM (the ladder uses
  *targeted* code/memory queries, not blob ingestion).

## 9. Risks & mitigations
| Risk | Mitigation |
|---|---|
| C# mod needs game + .NET toolchain | Mock proves the pipeline; mod ships as source, user-enabled; zero Python coupling. |
| `pythonnet` absent | `DotNetConnector` falls back to a curated CoQ schema. |
| Scope creep (all rungs at once) | Only CoQ rung wired end-to-end; others are interface-correct scaffolds. |
| CoQ version drift | Schema re-discoverable; bridge reads by field name, not offsets. |
| Ghidra mis-applied to managed/Lua games | Ladder routes Unity→.NET, LÖVE→Lua; Ghidra reserved for native binaries. |

## 10. How to run (demo)
```
# 1) headless pipeline (no game needed)
python -m tools.mock_coq_server --port 50545        # terminal A
python -m src.swarm --config configs/coq_qa.yaml --agents 3 --timesteps 8000 \
    --transport mock --dashboard                    # terminal B  (dashboard :8000)

# 2) real game
#   enable mods/CoQ_QA_Bridge in CoQ, start a run, then:
python -m src.swarm --config configs/coq_qa.yaml --agents 3 --transport live --dashboard
```

## 11. Future milestones
- Resolve Ghidra pointer maps → `pymem` runtime reads (native roguelikes).
- Lovely Lua bridge for Balatro (LÖVE rung).
- Vision rung: dxcam capture + `pydirectinput` + VLM HUD labeling (universal).
- Parallel swarm (Ray) + repro-trace export (action log per fault).
