# CI-friendly run summary

Date: 2026-06-17

Completed:

- `src/sdk/pipeline.py` now writes:
  - `run_summary.json`
  - `run_summary.md`
- Run summary includes:
  - run status;
  - validation status;
  - bug-found boolean;
  - validation errors/warnings;
  - report summary;
  - artifact paths.
- Added `bridge-maker run --fail-on-bug`.
- `--fail-on-bug` returns exit code `2` when oracle hits are present, while still
  writing the full report and run summary.
- Added tests for summary artifacts and bug-found state.
- Updated README, docs, status, and Ukrainian pitch.

Verification:

- `bridge-maker run --adapter examples\\buggy_roguelike.py --out runs\\ci_fail_demo --game-name "CI Fail Demo" --fail-on-bug`
- Verified exit code `2`.
- `python -m unittest tests.test_contract_sdk`

Product impact:

Bridge-Maker can now be used in CI/nightly jobs without scraping HTML. Developers
can choose whether bug discovery is a failing build condition.

