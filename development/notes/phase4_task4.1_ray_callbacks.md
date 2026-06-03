# Task 4.1 — Ray Callback Integrations

**File:** `src/ray_callbacks.py` → `DashboardBridgeCallbacks`

- `DefaultCallbacks` subclass (with a stand-in base when Ray is absent so the
  module still imports).
- `on_episode_step` streams agent coordinates + latest anomaly; `on_episode_end`
  pushes a full telemetry frame (player/goal/map/obstacles/bug_zones + ICM
  stats); `on_train_result` mines learner stats for curiosity loss and pushes
  scalar reward/curiosity via the new `DashboardServer.update_metrics`.
- Every hook is `**kwargs`-tolerant and wrapped so a telemetry error can never
  crash a rollout worker.
