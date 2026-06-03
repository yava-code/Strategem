# Task 3.3 — Distributed Training Infrastructure

**File:** `src/train_rllib.py` → `build_ppo_config`, `run_rllib_training`

- `--num-workers` fans rollouts across processes; tries `env_runners(...)`
  (new API) then `rollouts(num_rollout_workers=...)` (legacy) for version safety.
- `run_rllib_training` drives `algo.train()` for N iterations, logs mean episode
  return, checkpoints to `output_rllib_<mode>/`, and tears down Ray cleanly.

**Verified:** import + CLI fallback path exercised (Ray not installed locally).
