# Task 1.4 — Discovered State Mapping

**File:** `src/auto_analyzer.py` → `SchemaClassifier`, `TelemetryStrategy._assemble`

- New `SchemaClassifier` ingests raw frames from any strategy and infers
  `type`, observed `min`/`max`, semantic `role` (coordinate/health/time/scalar),
  `importance`, and a `normalize` block (`min_max` low/high).
- Access metadata threads through: memory `offset` (frida/pymem) or `json_path`
  (network), plus `source`.
- `_assemble` guarantees an identical `state_map.json` contract across all three
  strategies.

**Verified:** regenerated `state_map.json` now carries normalization limits +
json paths; round-trips through the agent generator.
