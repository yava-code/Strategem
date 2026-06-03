# MVP Step 4 — Integration Orchestrator

**File:** `src/orchestrator.py`

- Walks the connector ladder in reliability order (dotnet → lua → ghidra →
  vision) and picks the first that `detect`s the target; Vision terminates it.
- `discover()` writes `state_map.json`; `open_transport()` returns a live channel.
- CLI: `python -m src.orchestrator --target <game dir> --output state_map.json`.

**Verified:** on `D:\...\Caves of Qud` → matches `dotnet-mono`, writes schema.
