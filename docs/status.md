# Current Status

Last verified in this session:

- `python -m pip install -e . --no-deps` builds and installs editable package.
- `bridge-maker --help` works through the installed console script.
- `bridge-maker doctor --out runs\doctor_final_demo` reports core status `ok`.
- `python -m bridge_maker --help` works.
- `python -m bridge_maker init --help` works.
- `python -m bridge_maker validate --help` works.
- `python -m bridge_maker run --help` works.
- `python -m unittest discover -s tests` passes: 10 tests OK.
- Reproducible run verified:
  - `bridge-maker run --adapter examples\buggy_roguelike.py --out runs\trace_strategy_demo --game-name "Trace Strategy Demo" --trace-actions 24 --trace-strategy random --seed 42`
  - `report.json` summary stores `trace_strategy=random` and `trace_seed=42`.
- CI failure mode verified:
  - `bridge-maker run --adapter examples\buggy_roguelike.py --out runs\ci_fail_demo --game-name "CI Fail Demo" --fail-on-bug`
  - command returns exit code `2` when oracle hits are found and still writes reports.
- GitHub Actions workflow scaffold verified:
  - `bridge-maker init-ci --adapter examples\buggy_roguelike.py --out runs\ci_template_demo\bridge-maker.yml --run-dir runs\nightly_demo --trace-actions 77 --seed 11`
  - generated workflow uses `doctor`, `run --fail-on-bug`, and `actions/upload-artifact`.
- First-run path works:
  - `bridge-maker init --out runs\package_demo\starter --game-name "Package Quest"`
  - `bridge-maker smoke --adapter runs\package_demo\starter\bridge_adapter.py --steps 6`
  - `bridge-maker run --adapter runs\package_demo\starter\bridge_adapter.py --out runs\package_demo\contract --game-name "Package Quest"`
- `python -m bridge_maker demo --out runs/docs_demo` produces:
  - annotation suggestions;
  - `state_map.json`;
  - `action_map.json`;
  - `oracle_map.json`;
  - `trace.jsonl`;
  - generated SDK env;
  - `report.html`.

## Ready

- SDK decorators.
- Installable Python package metadata via `pyproject.toml`.
- Console command: `bridge-maker`.
- Environment diagnostics via `bridge-maker doctor`.
- GitHub Actions workflow generation via `bridge-maker init-ci`.
- Starter adapter scaffold via `bridge-maker init`.
- Adapter quality checks via `bridge-maker validate`.
- One-command basic QA via `bridge-maker run`.
- Reproducible trace controls: `--trace-actions`, `--trace-strategy`, `--seed`.
- CI summary artifacts: `run_summary.json`, `run_summary.md`, and `--fail-on-bug`.
- Contract registry.
- Adapter loader.
- Contract export.
- SDK Gymnasium smoke env.
- Deterministic annotation suggestions.
- Static JSON/HTML report generation.
- Reproduction evidence in reports: action steps, previous state, and failing state.
- Buggy roguelike proof demo.
- Noita WebSocket adapter boundary test with fake client.

## Experimental / optional

- CE MCP and Ghidra MCP grey-box assist.
- Pymem generated live env.
- Ray/RLlib trainer.
- Oracle/dashboard integration.

These are valuable, but the public MVP story should focus on the stable contract
and report loop.
