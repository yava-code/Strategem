# Task 3.2 — Built-in Curiosity Models

**File:** `src/train_rllib.py` → `build_ppo_config`

- Attaches RLLib's built-in `Curiosity` exploration with `eta`, `lr`,
  `feature_dim`, and forward/inverse net layouts pulled from the YAML `icm`
  block (same hyperparameters as our standalone ICM).
- Pins the old API stack (`api_stack(enable_rl_module_and_learner=False, ...)`)
  because built-in Curiosity is an old-stack feature; wrapped in try/except for
  version tolerance.

PPO hyperparameters (lr, gamma, batch, epochs, entropy) sourced from `SDKConfig`.
