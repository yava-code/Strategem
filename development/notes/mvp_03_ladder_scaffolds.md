# MVP Step 3 — Ladder scaffolds (Ghidra / Lua / Vision)

**Files:** `src/connectors/{ghidra,lua,vision}_connector.py`

- `GhidraConnector` (native rung): real HTTP client to the GhidraMCP bridge
  (`searchFunctions`/`strings`), ranks coordinate/health symbols into a schema;
  `open_transport` raises a clear `NotImplementedError` (needs Ghidra→pymem
  pointer map). Not used for Unity/LÖVE — documented why.
- `LuaBridgeConnector` (LÖVE/Balatro): **really** opens the fused `.exe` as a zip,
  scans bundled `.lua` for state keywords → schema; transport via Lovely mod.
- `VisionConnector` (universal fallback): engine-agnostic detect; declares VLM-HUD
  scalars; transport raises `NotImplementedError` (capture+VLM milestone).

No placeholder comments — unfinished runtime paths raise actionable errors.
