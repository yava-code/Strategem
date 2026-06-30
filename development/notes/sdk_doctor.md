# SDK doctor command

Date: 2026-06-17

Completed:

- Added `src/sdk/doctor.py`.
- Added `bridge-maker doctor`.
- Doctor checks:
  - Python version;
  - `bridge-maker` console script on PATH;
  - installed package version;
  - core imports: `bridge_maker`, `gymnasium`, `numpy`, `pydantic`;
  - optional extras groups: `training`, `greybox`, `mlops`, `noita`.
- Doctor writes:
  - `doctor_report.json`;
  - `doctor_report.md`.
- Added tests for doctor report shape and file output.
- Updated README, docs, status, and Ukrainian pitch.

Verification:

- `bridge-maker doctor --out runs\\doctor_demo`
- `python -m unittest tests.test_contract_sdk`

Product impact:

This gives users and support a quick environment sanity check. Missing optional
extras are visible but do not make the core SDK look broken.

