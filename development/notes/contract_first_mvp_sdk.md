# Contract-First MVP SDK

Completed on 2026-06-14.

## Implemented

- Created the SDK contract layer:
  - `bridge_maker/__init__.py` exposes the user-facing `from bridge_maker import bm` import.
  - `src/sdk/annotations.py` exposes the public `bm` decorator namespace.
  - `src/sdk/specs.py` stores state/action/event/oracle/reset/snapshot metadata.
  - `src/sdk/runtime.py` samples state, invokes actions, evaluates oracles, and writes trace frames.
  - `src/sdk/export.py` exports `state_map.json`, `action_map.json`, `oracle_map.json`, `trace.jsonl`, and `contract.json`.
  - `src/sdk/env.py` provides a direct Gymnasium env over SDK/adapter functions.
  - `src/sdk/scout.py` provides deterministic AST annotation suggestions.
  - `src/bridge_maker.py` is the contract-first CLI.
- Added `examples/annotated_dummy.py` as the canonical no-MCP smoke target.
- Added `adapters/noita/bridge_template.py` and README as the NoitaRL adapter shape.
- Replaced the old CoQ/socket PRD with a new contract-first `PRD.md`.
- Extended `StateVariable` with SDK source metadata fields.

## Verified

- `python -m compileall bridge_maker src examples adapters`
- `python -m bridge_maker --help`
- `python -m src.bridge_maker --help`
- `python -m src.bridge_maker suggest --repo examples --out runs\dummy_suggestions`
- `python -m src.bridge_maker export --adapter examples/annotated_dummy.py --out runs/dummy --game-name annotated_dummy`
- `python -m src.bridge_maker generate --contract runs/dummy`
- `python -m src.bridge_maker smoke --adapter examples/annotated_dummy.py --steps 20`
- `StateMap.load("runs/dummy/state_map.json")`

## Result

The SDK/adapter path now works without Cheat Engine, Ghidra, Ray, Wandb, Modal, or Azure. The exported dummy contract has 5 observation fields, 5 actions, 1 oracle, 1 event, and a trace log.

## Next

- Add tests around the SDK exporter and `SDKGymEnv`.
- Connect `swarm_trainer.py` to SDK-generated env wrappers, not only the current pymem `LiveEnv`.
- Build the real NoitaRL adapter once the project path/API is available.

## 2026-06-16 grant-demo hardening

- Added `examples/buggy_roguelike.py`, a tiny annotated roguelike with an intentional right-edge movement bug.
- Added `src/sdk/report.py` for JSON/HTML reports from exported contracts and traces.
- Added `python -m bridge_maker report` and `python -m bridge_maker demo`.
- Updated trace generation to stress actions in short bursts so oracle bugs are actually exercised.
- Rebuilt the grant demo at `runs/grant_demo`:
  - 5 state fields,
  - 4 actions,
  - 2 oracles,
  - 13 trace frames,
  - 3 `out_of_bounds` oracle hits.
- Added `grant_materials/bridge_maker_grant_presentation.pptx` and `grant_materials/proof_of_work.md`.
- Removed stale CoQ/socket/checkpoint/state-map artifacts from the active tree.

## 2026-06-16 external adapter proof

- Inspected `probable-basilisk/noita-ws-api` locally at commit `47054b0`.
- Added `adapters/noita_ws/README.md` documenting how the WebSocket/Lua bridge maps into Bridge-Maker's contract model.
- Reworked `adapters/noita/bridge_template.py` into a `Protocol`-based binder instead of fake placeholder methods.
- Added `tests/test_contract_sdk.py` to lock the SDK MVP:
  - contract export,
  - `StateMap` validation,
  - JSON/HTML report generation,
  - generated SDK env import,
  - direct `SDKGymEnv` smoke,
  - deterministic CodeScout suggestions.
- Added `adapters/noita_ws/session.py` and `tests/test_noita_ws_session.py`:
  - Python-side WebSocket server waits for Noita-style heartbeat,
  - raw Lua eval commands round-trip through a fake Noita client,
  - BridgeRuntime samples and steps over the WebSocket-backed adapter contract.
