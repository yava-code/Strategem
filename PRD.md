# PRD - The Bridge-Maker Contract-First MVP

**Status:** MVP proof implemented  
**Owner:** Varfolomiy  
**Last updated:** 2026-06-14  

---

## 1. Problem

Indie developers need automated QA that explores their game overnight and returns useful bug evidence. Fully automatic binary reverse engineering is too fragile for normal onboarding: CE/Ghidra setup, pointer stability, action discovery, and GUI state are all sharp edges.

The product needs a smaller, honest contract: developers expose the gameplay semantics they already know, and Bridge-Maker automates the rest.

---

## 2. Product

Bridge-Maker is a contract-first QA/RL framework.

1. The developer or adapter author marks existing state/action/oracle functions with lightweight decorators.
2. Bridge-Maker exports `state_map.json`, `action_map.json`, `oracle_map.json`, and `trace.jsonl`.
3. The SDK runtime exposes the contract as a Gymnasium environment.
4. Existing RL/dashboard/reporting layers can train agents and surface bug evidence.
5. CE/Ghidra/VLM remain optional assist tools for missing or suspicious contract points.

---

## 3. Primary User

- **Indie developer:** wants a low-friction overnight tester without learning RLlib, PDDL, or reverse engineering.
- **Reverse project maintainer:** wants to expose known memory/action hooks as a reusable QA adapter.
- **AI/QA researcher:** wants a clean semantic interface for experiments.

---

## 4. MVP Scope

Built in this MVP:

- Python decorator namespace `bm`.
- Registry for state, action, event, oracle, reset, and snapshot hooks.
- Adapter loader from a Python file path.
- Contract exporter.
- Direct SDK Gymnasium environment.
- Deterministic CodeScout v0 for annotation suggestions.
- JSON/HTML report generation from traces.
- One-command proof demo over an annotated buggy roguelike.
- Annotated dummy target.
- NoitaRL adapter template.
- Noita WebSocket API readiness note from inspection of `probable-basilisk/noita-ws-api` commit `47054b0`.
- Executable Noita WebSocket adapter-boundary test with fake heartbeat/reply client.

Not built in this MVP:

- Engine-native C#/Lua attributes.
- Live NoitaRL / Noita WebSocket binding.
- PDDL generation.
- Automatic CE/Ghidra discovery as default onboarding.
- Full overnight HTML report.

---

## 5. Success Criteria

1. `python -m bridge_maker --help` shows the product CLI.
2. `python -m bridge_maker suggest --repo examples` writes suggestion files.
3. `python -m bridge_maker export --adapter examples/annotated_dummy.py --out runs/dummy` writes all contract files.
4. The exported `state_map.json` validates against `StateMap`.
5. `python -m bridge_maker smoke --adapter examples/annotated_dummy.py` runs a 20-step Gymnasium loop without CE, Ghidra, Ray, Wandb, Modal, or Azure.
6. `python -m bridge_maker demo --out runs/grant_demo` produces a report with at least one oracle finding on `examples/buggy_roguelike.py`.
7. `python -m unittest discover -s tests` passes without CE, Ghidra, Ray, Wandb, Modal, or Azure.
8. `tests/test_noita_ws_session.py` proves the Noita WebSocket adapter boundary without requiring the Noita game runtime.

---

## 6. Product Direction

The old CoQ/socket PRD was removed from the active tree. The active direction is SDK/Adapter-first. The grey-box stack remains valuable, but it is now an assist path rather than the main promise.
