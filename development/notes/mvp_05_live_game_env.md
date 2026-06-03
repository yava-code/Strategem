# MVP Step 5 — LiveGameEnv

**File:** `src/live_game_env.py`

- `gym.Env` over any `GameTransport`. Builds the observation vector from the
  `state_map` (min-max normalization), tracks coordinate/health channels for the
  spatial grid, and reuses `MultiObjectiveRewardGenerator` + ICM + `SDKLogger`.
- Transport `anomaly` flags become `log_anomaly` events; `reward_hint` is added to
  the curiosity/QA reward.
- Action count now flows through to the ICM (see reward_generator change) so
  non-5-action games (CoQ has 6) train correctly.

**Verified:** trains under SB3 PPO over the mock; logs positions + anomalies.
