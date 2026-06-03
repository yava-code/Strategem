# Task 5.1 — ML-Agents / Godot RL Adaptor

**File:** `src/engine_bridges.py` → `MLAgentsGymAdaptor`, `GodotRLGymAdaptor`

- Adapter pattern: both subclass `gym.Env` and normalize their engine wrappers
  onto the Gymnasium 5-tuple.
- `MLAgentsGymAdaptor` wraps `UnityToGymWrapper` and rebases the legacy 4-tuple
  (collapses done → terminated/truncated using `TimeLimit.truncated`).
- `GodotRLGymAdaptor` wraps `GodotEnv` and forwards its native 5-tuple.
- Both import-guard their SDKs and raise actionable errors only on `connect()`.
