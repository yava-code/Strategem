# MVP Step 6 — QA Swarm

**File:** `src/swarm.py`, `configs/coq_qa.yaml`

- Loads base YAML + per-agent `overrides` (dotted-key deep-set, in-memory
  `SDKConfig(raw_config=...)`), discovers schema via the orchestrator, then trains
  N PPO testers, each its own socket + logger.
- Profiles: `exploit_hunter` (PPO, high exploration/bug reward), `speedrunner`
  (PPO, movement-greedy), `chaos_monkey` (`policy: random` — a pure fuzzer, which
  reliably sweeps a bounded zone where a greedy policy fixates on one fault).
- QA reward fixes that made multi-fault discovery reliable: the bug reward fires
  **once per distinct fault** (no farming the nearest bug — see `live_game_env`),
  and `persist_exploration: true` keeps the novelty map across episodes.
- Per-tester heatmap + anomaly report; aggregate `swarm_report.json`; live roster
  pushed to the dashboard.

**Verified:** 3 testers × 8k steps over the mock surfaced **all 3 fault classes**
(`HAZARD_DAMAGE`, `SOFTLOCK_SUSPECTED`, `CRASH_NUMERIC`) across 3 consecutive clean
runs. No single tester finds everything — the swarm union does (the whole point).
