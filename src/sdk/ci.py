from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def write_github_actions_workflow(
    output: str | Path,
    *,
    adapter: str,
    run_dir: str = "runs/bridge_maker_ci",
    python_version: str = "3.12",
    trace_actions: int = 200,
    trace_strategy: str = "random",
    seed: int = 42,
    fail_on_bug: bool = True,
    force: bool = False,
) -> Path:
    path = Path(output).resolve()
    if path.exists() and not force:
        raise FileExistsError(f"Workflow already exists: {path}. Re-run with --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _workflow_template(
            adapter=adapter,
            run_dir=run_dir,
            python_version=python_version,
            trace_actions=trace_actions,
            trace_strategy=trace_strategy,
            seed=seed,
            fail_on_bug=fail_on_bug,
        ),
        encoding="utf-8",
    )
    return path


def _workflow_template(
    *,
    adapter: str,
    run_dir: str,
    python_version: str,
    trace_actions: int,
    trace_strategy: str,
    seed: int,
    fail_on_bug: bool,
) -> str:
    fail_flag = " --fail-on-bug" if fail_on_bug else ""
    adapter_path = _ci_path(adapter)
    run_path = _ci_path(run_dir)
    return dedent(
        f"""\
        name: Bridge-Maker QA

        on:
          workflow_dispatch:
          pull_request:
          schedule:
            - cron: "0 3 * * *"

        jobs:
          bridge-maker:
            runs-on: ubuntu-latest
            timeout-minutes: 20

            steps:
              - name: Checkout
                uses: actions/checkout@v4

              - name: Set up Python
                uses: actions/setup-python@v5
                with:
                  python-version: "{python_version}"

              - name: Install Bridge-Maker project
                run: |
                  python -m pip install --upgrade pip
                  pip install -e .

              - name: Diagnose SDK install
                run: bridge-maker doctor --out {run_path}/doctor

              - name: Run Bridge-Maker QA
                run: >
                  bridge-maker run
                  --adapter {adapter_path}
                  --out {run_path}
                  --trace-actions {trace_actions}
                  --trace-strategy {trace_strategy}
                  --seed {seed}{fail_flag}

              - name: Upload Bridge-Maker artifacts
                if: always()
                uses: actions/upload-artifact@v4
                with:
                  name: bridge-maker-report
                  path: {run_path}
        """
    )


def _ci_path(path: str) -> str:
    return path.replace("\\", "/")
