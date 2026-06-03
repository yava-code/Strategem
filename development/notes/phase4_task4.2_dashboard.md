# Task 4.2 — Web Dashboard UI

**File:** `src/dashboard.py`

- Added `DashboardServer.update_metrics(step, extrinsic, intrinsic, loss)` — a
  scalar-only update that leaves map geometry intact (used by `on_train_result`).
- Fixed a latent `Optional` import (annotation was unresolved).
- Existing glassmorphic SSE/canvas UI (reward chart, coverage map, anomaly
  stream) is fed by both the SB3 callback and the new RLLib callbacks, so the
  console works for either training backend.

**Verified:** dashboard imports clean; `update_metrics` exercised via callbacks.
