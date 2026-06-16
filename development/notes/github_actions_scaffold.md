# GitHub Actions scaffold

Date: 2026-06-17

Completed:

- Added `src/sdk/ci.py`.
- Added `bridge-maker init-ci`.
- Generated workflow runs:
  - checkout;
  - Python setup;
  - `pip install -e .`;
  - `bridge-maker doctor`;
  - `bridge-maker run --fail-on-bug`;
  - artifact upload with `if: always()`.
- Workflow generator normalizes Windows paths to POSIX paths for GitHub's Ubuntu runner.
- Added tests for workflow contents and overwrite safety.
- Updated README, docs, status, and Ukrainian pitch.

Verification:

- `bridge-maker init-ci --adapter examples\\buggy_roguelike.py --out runs\\ci_template_demo\\bridge-maker.yml --run-dir runs\\nightly_demo --trace-actions 77 --seed 11`
- `python -m unittest tests.test_contract_sdk`

Product impact:

This lowers friction for teams that want Bridge-Maker in pull requests or
nightly jobs. They do not need to write GitHub Actions YAML from scratch.

