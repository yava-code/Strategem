# MVP Step 8 — Multi-agent dashboard + PRD

**Files:** `src/dashboard.py`, `PRD.md`

- Dashboard: added an `agents` roster to the telemetry store, `update_agent()`,
  a `/api/swarm` endpoint, and a "QA Swarm Testers" card + `updateSwarm()` poller.
  Existing glassmorphic UI (reward chart, coverage map, anomaly stream) untouched.
- `PRD.md`: full product requirements — problem, ladder architecture, CoQ
  rationale, scope split, met success criteria, risks, run instructions, roadmap.

**Verified:** `/api/swarm` returns the roster; card + JS render; reused by the
swarm callback.
