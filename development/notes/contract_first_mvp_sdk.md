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
- Renamed the old CoQ/socket PRD to `PRD_old_coq_socket.md` and added a new contract-first `PRD.md`.
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
