# Actionable bug reports

Date: 2026-06-17

Completed:

- Enhanced `src/sdk/report.py`.
- Oracle findings in `report.json` now include:
  - `previous_state`;
  - `repro_steps`;
  - failing `state`;
  - triggering `action`.
- Report summary now includes:
  - `validation_status`;
  - `first_issue_frame`;
  - `first_issue`.
- `report.html` now renders issue cards with:
  - reproduction actions;
  - previous state;
  - failing state.
- Added test coverage for reproduction evidence.
- Updated README, docs, status, and Ukrainian pitch.

Verification:

- `bridge-maker run --adapter examples\\buggy_roguelike.py --out runs\\report_evidence_demo --game-name "Evidence Demo"`
- `python -m unittest tests.test_contract_sdk`

Product impact:

The report is now closer to what an indie developer needs in the morning: not
just "an oracle fired", but the short sequence of actions and state transition
that made the bug visible.

