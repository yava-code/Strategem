# Task 3.1 — RLLib Environment Registration

**File:** `src/train_rllib.py` → `register_environment`, `_make_env`

- `_make_env(env_config)` builds either the standard or auto-generated env per
  worker from `config_path` + `generated` flag, each with its own `SDKLogger`.
- Registered under `ENV_ID = "bridge_maker_env"` via `tune.registry.register_env`.

Ray is import-guarded (`RAY_AVAILABLE`); CLI prints install guidance and points
to the SB3 path when Ray is missing.
