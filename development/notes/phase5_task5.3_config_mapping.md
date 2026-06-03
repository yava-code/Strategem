# Task 5.3 — Unified Configuration Mappings

**File:** `src/engine_bridges.py` → `EngineConfigMapper`

- One YAML reward profile → engine-side config for all three engines:
  - `to_unity_mlagents()` — ML-Agents behavior block (trainer + reward_signals +
    reward_weights).
  - `to_unreal()` — UE5 Learning Agents reward profile.
  - `to_godot()` — Godot RL sync config.
- `export(engine)` dispatch + CLI (`--engine unity|unreal|godot`, optional
  `--output`).

**Verified:** all three exports render correctly for both `qa` and `npc` configs.
