# Adapter validation command

Date: 2026-06-17

Completed:

- Added `src/sdk/validation.py`.
- Added `python -m bridge_maker validate`.
- Validator checks:
  - adapter import;
  - state/action/oracle counts;
  - reset/sample execution;
  - numeric/boolean MVP state compatibility;
  - oracle execution;
  - short cyclic action smoke loop;
  - missing bounds/reset/snapshot warnings.
- Validator can write:
  - `validation_report.json`
  - `validation_report.md`
- Added tests for:
  - ready starter adapter;
  - broken adapter missing actions and oracles.
- Updated README, docs site, Ukrainian pitch, and generated starter quickstart.

Product impact:

This gives indie developers a predictable checkpoint between annotation and
export/report generation. Instead of discovering contract problems through long
tracebacks or empty reports, they get direct guidance: what is missing, what is
only a warning, and whether the adapter is ready for useful QA evidence.

