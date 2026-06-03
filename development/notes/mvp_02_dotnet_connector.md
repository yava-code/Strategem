# MVP Step 2 — DotNet/Mono connector (active CoQ rung)

**File:** `src/connectors/dotnet_connector.py`

- `detect`: `MonoBleedingEdge` dir + `*/Managed/Assembly-CSharp.dll`.
- `discover_schema`: curated 9-var CoQ schema (hp, hp_max, x, y, depth, hunger,
  level, turn, threats) with roles/normalization + the `csharp_path` each value
  comes from. Optional `pythonnet` reflection confirms the relevant managed types
  and flags `reflection_confirmed`.
- `open_transport`: returns a ready `SocketTransport` (each swarm worker connects
  its own socket).

**Verified:** orchestrator on the real CoQ install →
`unity-mono`, 9 obs dims; works with pythonnet absent (curated fallback).
