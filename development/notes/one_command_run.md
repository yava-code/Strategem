# One-command basic QA run

Date: 2026-06-17

Completed:

- Added `src/sdk/pipeline.py`.
- Added `python -m bridge_maker run`.
- The command performs the basic product workflow:
  - validate adapter;
  - stop on validation errors by default;
  - export contract files;
  - generate SDK env wrapper;
  - generate JSON/HTML report.
- Updated `init` next-step output to point at `run`.
- Added tests for:
  - successful one-command run;
  - validation-gated failed run.
- Updated README, docs site, status page, Ukrainian pitch, and generated starter guide.

Product impact:

Bridge-Maker now has a simpler buyer-facing path:

```powershell
python -m bridge_maker init --out bridge_maker_starter --game-name "My Game"
python -m bridge_maker smoke --adapter bridge_maker_starter\bridge_adapter.py --steps 12
python -m bridge_maker run --adapter bridge_maker_starter\bridge_adapter.py --out runs\my_game --game-name "My Game"
```

The separate `validate`, `export`, `generate`, and `report` commands remain
available for CI and debugging, but the first useful result no longer requires
the user to memorize the internal pipeline.

