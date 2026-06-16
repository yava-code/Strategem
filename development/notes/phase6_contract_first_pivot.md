# Phase 6 Note - Contract-First Pivot

Completed on 2026-06-14.

## What changed

- Archived the previous universal CE/Ghidra-first roadmap by renaming `master_roadmap_v2.md` to `master_roadmap_v2_old.md`.
- Added `master_roadmap_v3.md` as the current proposed plan.
- Reframed Bridge-Maker as an SDK/Adapter-first QA/RL framework:
  - decorators/attributes expose state, actions, events, and oracles;
  - agents inspect code and traces to suggest missing annotations;
  - CE/Ghidra/VLM remain optional grey-box assist tools, not the default path.

## Why

The live experiments showed that the post-contract stack works: `state_map.json`, env generation, Ray/RLlib, dashboard, and oracle reporting. The fragile part is fully automatic semantic discovery from arbitrary binaries. The new plan makes the semantic contract explicit and lightweight instead of hiding reverse engineering complexity behind a fake one-click promise.

## Research note

The paper `2402.12393v2.pdf` argues for game logs plus action-model learning for regression testing, but depends on PDDL modeling. Bridge-Maker takes the same core insight, developer-provided semantic traces are necessary, and replaces PDDL with simple decorators/adapters plus agent-assisted contract synthesis.
