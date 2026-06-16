# First-run starter scaffold

Date: 2026-06-17

Completed:

- Added `src/sdk/scaffold.py`.
- Added `python -m bridge_maker init`.
- The command writes:
  - `bridge_adapter.py`
  - `BRIDGE_MAKER_QUICKSTART.md`
- The starter adapter is executable immediately and exposes:
  - health;
  - position;
  - turn counter;
  - movement/wait actions;
  - two bug oracles.
- Added coverage in `tests/test_contract_sdk.py`.
- Updated README and docs to make the product first-run path:
  - `init`
  - `smoke`
  - `export`
  - `report`

Verification:

- `python -m bridge_maker --help`
- `python -m unittest discover -s tests` -> 5 tests OK.
- Fresh first-run path verified under `runs/init_demo`.

Product impact:

This reduces onboarding friction. A developer no longer has to infer adapter shape
from the demo project. They can generate a local starter, run it, then replace
the bridge class internals with calls into their own game/debug API/test harness.

