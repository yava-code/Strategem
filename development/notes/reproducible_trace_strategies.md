# Reproducible trace strategies

Date: 2026-06-17

Completed:

- Added deterministic trace action planning in `src/sdk/export.py`.
- Supported strategies:
  - `burst` - default, preserves existing behavior;
  - `cycle` - evenly cycles through actions;
  - `random` - seeded pseudo-random action order.
- Exposed controls in CLI:
  - `--trace-actions`
  - `--trace-strategy`
  - `--seed`
- Persisted trace metadata in `contract.json`.
- Added trace metadata to `report.json` summary.
- Added tests for reproducible random planning and report metadata.
- Updated README, docs, status, and Ukrainian pitch.

Product impact:

Bridge-Maker runs are now easier to reproduce. A developer can run a longer
random exploration with a fixed seed, share the report, and re-run the same
action plan later while debugging.

