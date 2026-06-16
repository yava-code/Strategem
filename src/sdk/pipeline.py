from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.sdk.export import export_contract
from src.sdk.generator import generate_sdk_env
from src.sdk.report import build_report
from src.sdk.validation import ValidationReport, validate_adapter


@dataclass(frozen=True)
class QARunResult:
    status: str
    out_dir: Path
    validation: ValidationReport
    paths: dict[str, Path]
    report_summary: dict[str, Any] | None = None

    @property
    def ready(self) -> bool:
        return self.status == "complete"

    @property
    def bug_found(self) -> bool:
        return bool(self.report_summary and self.report_summary.get("status") == "bug_found")

    def to_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ready": self.ready,
            "bug_found": self.bug_found,
            "out_dir": str(self.out_dir),
            "validation_status": self.validation.status,
            "validation_errors": [f.__dict__ for f in self.validation.errors],
            "validation_warnings": [f.__dict__ for f in self.validation.warnings],
            "report_summary": self.report_summary,
            "artifacts": {key: str(path) for key, path in self.paths.items()},
        }


def run_basic_qa(
    adapter: str | Path,
    out_dir: str | Path,
    *,
    game_name: str | None = None,
    validate_steps: int = 6,
    trace_actions: int = 12,
    trace_strategy: str = "burst",
    trace_seed: int | None = None,
    continue_on_validation_errors: bool = False,
) -> QARunResult:
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    validation = validate_adapter(adapter, steps=validate_steps, out_dir=out)
    paths: dict[str, Path] = {
        "validation_json": out / "validation_report.json",
        "validation_md": out / "validation_report.md",
    }

    if validation.errors and not continue_on_validation_errors:
        result = QARunResult(
            status="validation_failed",
            out_dir=out,
            validation=validation,
            paths=paths,
        )
        _write_run_summary(result)
        return result

    contract_paths = export_contract(
        adapter,
        out,
        game_name=game_name,
        trace_actions=trace_actions,
        trace_strategy=trace_strategy,
        trace_seed=trace_seed,
    )
    env_path = generate_sdk_env(out)
    report_paths = build_report(out)

    paths.update(contract_paths)
    paths["sdk_env"] = env_path
    paths.update(report_paths)
    result = QARunResult(
        status="complete" if not validation.errors else "complete_with_validation_errors",
        out_dir=out,
        validation=validation,
        paths=paths,
        report_summary=_load_report_summary(report_paths["report_json"]),
    )
    _write_run_summary(result)
    return result


def _load_report_summary(report_json: Path) -> dict[str, Any] | None:
    if not report_json.exists():
        return None
    return json.loads(report_json.read_text(encoding="utf-8")).get("summary")


def _write_run_summary(result: QARunResult) -> None:
    json_path = result.out_dir / "run_summary.json"
    md_path = result.out_dir / "run_summary.md"
    result.paths["run_summary_json"] = json_path
    result.paths["run_summary_md"] = md_path
    data = result.to_summary()
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    md_path.write_text(_render_run_summary(data), encoding="utf-8")


def _render_run_summary(data: dict[str, Any]) -> str:
    report = data.get("report_summary") or {}
    lines = [
        "# Bridge-Maker Run Summary",
        "",
        f"- Status: **{data['status']}**",
        f"- Validation: **{data['validation_status']}**",
        f"- Bug found: **{data['bug_found']}**",
        f"- Report status: **{report.get('status', 'not_generated')}**",
        f"- Oracle hits: **{report.get('oracle_hits', 0)}**",
        f"- First issue: **{report.get('first_issue') or 'none'}**",
        "",
        "## Artifacts",
        "",
    ]
    for key, path in data["artifacts"].items():
        lines.append(f"- `{key}`: `{path}`")
    if data["validation_errors"]:
        lines.extend(["", "## Validation Errors", ""])
        for err in data["validation_errors"]:
            lines.append(f"- `{err['code']}`: {err['message']}")
    return "\n".join(lines) + "\n"
