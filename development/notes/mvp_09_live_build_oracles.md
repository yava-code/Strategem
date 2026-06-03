# MVP Step 9 — Live build: real CoQ API, oracles, compiled & installed

**Files:** `mods/CoQ_QA_Bridge/QABridge.cs`, `src/connectors/dotnet_connector.py`,
`tools/mock_coq_server.py`

Goal: move the CoQ rung from "plausible source" to "compiles against the real
game", and add the oracle layer that turns exploration into *testing*.

- **Ground-truth API via reflection.** Used `dotnet` (net10) to reflect over the
  real `Assembly-CSharp.dll` (PowerShell reflection stack-overflowed on the
  resolve event; a compiled probe worked). Corrected the mod to the real surface:
  `XRLCore.PlayerTurn()` exists; `The.Player` / `The.PlayerCell`; `Cell.X/Y`
  public fields; `GetStat("Hitpoints").Value/.BaseValue`; `GetPart<Stomach>()
  .HungerLevel`; `Zone.GetObjectsWithPart("Brain")` + `IsHostileTowards`;
  `GameObject.Move(dir, ...optional)` and `AutoMove(dir)` — there is **no**
  `Move(string)`-only overload as I'd first guessed.
- **Oracles added** (the answer to "it just presses random buttons"):
  EXCEPTION (Harmony `Finalizer` captures turn crashes, rethrows), INVARIANT
  (HP<0 / no cell / out-of-zone), SOFTLOCK (no movement N turns).
- **8-direction action set** (`MOVE_N..SW` + `WAIT` = 9) aligned across the mod,
  `DotNetConnector.ACTION_BINDINGS`, and the mock `DELTAS`.
- **Compiled-validated:** `dotnet build` of `QABridge.cs` against
  `Assembly-CSharp.dll` + `0Harmony.dll` + `UnityEngine.CoreModule.dll` → **0
  errors**. Installed to `%USERPROFILE%\AppData\LocalLow\Freehold Games\
  CavesOfQud\Mods\CoQ_QA_Bridge\`.

**Verified:** orchestrator → 9-dim schema, 9 actions; swarm × 8k over the mock
still finds all 3 fault classes; synthetic `src/train` unaffected.

**Still requires a human:** launching CoQ, enabling the mod, and starting a
character (interactive GUI) — only then does `--transport live` connect. The mod
hasn't been exercised at runtime inside a live game from here.
