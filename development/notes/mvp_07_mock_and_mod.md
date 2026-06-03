# MVP Step 7 — Mock server + CoQ Bridge mod

**Files:** `tools/mock_coq_server.py`, `mods/CoQ_QA_Bridge/*`

- `mock_coq_server.py`: protocol-accurate sim (threaded TCP) emitting the exact
  `coq_*` schema. Simulates a compact 28×16 starting room (CoQ zones are 80×25 but
  the player starts in a room) so the QA sweep is tractable, with three spread
  fault regions (west softlock band, east lava band, NE crash corner) — verifies
  the whole pipeline headless. NOTE: run ONE instance; SO_REUSEADDR lets several
  bind the same port and race, so clear the port between runs.
- `mods/CoQ_QA_Bridge`: complete Harmony mod. Background `TcpListener` queues
  requests; a postfix on `XRLCore.PlayerTurn` drains them on the main thread,
  applies the action, and replies with state read by field name off `The.Player`.
  Same wire format as the mock → `--transport live` needs zero Python changes.

**Verified:** mock drives the swarm end-to-end. Mod ships as source (user enables
in-game; cannot be compiled headless here — documented in its README).
