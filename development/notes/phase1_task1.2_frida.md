# Task 1.2 — Frida Hook Injector

**File:** `src/auto_analyzer.py` → `FridaHookingStrategy`

- JS payload hooks `Transform`-style getters and `send()`s agent/player X-Y plus
  health read off the instance pointer at fixed field offsets.
- Python side wires an `on("message")` collector that feeds live frames into the
  `SchemaClassifier`; offsets recorded as access metadata (`offset`, `source`).
- IL2CPP (`GameAssembly.dll`) and Unreal `AActor::GetActorLocation` are the
  documented hook targets.

**Verified:** runs with graceful fallback when `frida` is absent → 5-dim schema
with hex offsets.
