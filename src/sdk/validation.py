from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.sdk.loader import load_adapter
from src.sdk.runtime import BridgeRuntime, StateView
from src.sdk.specs import REGISTRY


@dataclass(frozen=True)
class ValidationFinding:
    severity: str
    code: str
    message: str
    detail: str = ""


@dataclass(frozen=True)
class ValidationReport:
    adapter: str
    status: str
    counts: dict[str, int]
    sample_state: dict[str, Any]
    reset_oracle_hits: list[dict[str, Any]]
    action_steps: list[dict[str, Any]]
    findings: list[ValidationFinding]

    @property
    def errors(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ready"] = self.status == "ready"
        return data


def validate_adapter(
    adapter: str | Path,
    *,
    steps: int = 6,
    out_dir: str | Path | None = None,
) -> ValidationReport:
    adapter_path = Path(adapter).resolve()
    findings: list[ValidationFinding] = []
    sample_state: dict[str, Any] = {}
    reset_hits: list[dict[str, Any]] = []
    action_steps: list[dict[str, Any]] = []

    try:
        load_adapter(adapter_path)
    except Exception as exc:
        report = ValidationReport(
            adapter=str(adapter_path),
            status="needs_work",
            counts={"states": 0, "actions": 0, "oracles": 0, "events": 0},
            sample_state={},
            reset_oracle_hits=[],
            action_steps=[],
            findings=[
                ValidationFinding(
                    "error",
                    "adapter_load_failed",
                    "Adapter could not be imported.",
                    f"{type(exc).__name__}: {exc}",
                )
            ],
        )
        _write_report(report, out_dir)
        return report

    counts = {
        "states": len(REGISTRY.states),
        "actions": len(REGISTRY.actions),
        "oracles": len(REGISTRY.oracles),
        "events": len(REGISTRY.events),
    }
    _check_contract_shape(counts, findings)
    _check_specs(findings)

    runtime = BridgeRuntime()
    try:
        sample_state = runtime.reset()
    except Exception as exc:
        findings.append(
            ValidationFinding(
                "error",
                "reset_or_sample_failed",
                "Bridge-Maker could not reset or sample adapter state.",
                f"{type(exc).__name__}: {exc}",
            )
        )

    if sample_state:
        _check_state_values(sample_state, findings)
        reset_hits = _check_oracles(sample_state, findings)
        action_steps = _run_action_smoke(runtime, sample_state, steps, findings)

    status = "ready" if not any(f.severity == "error" for f in findings) else "needs_work"
    report = ValidationReport(
        adapter=str(adapter_path),
        status=status,
        counts=counts,
        sample_state=sample_state,
        reset_oracle_hits=reset_hits,
        action_steps=action_steps,
        findings=findings,
    )
    _write_report(report, out_dir)
    return report


def _check_contract_shape(counts: dict[str, int], findings: list[ValidationFinding]) -> None:
    if counts["states"] == 0:
        findings.append(ValidationFinding("error", "no_states", "No state annotations registered."))
    if counts["actions"] == 0:
        findings.append(ValidationFinding("error", "no_actions", "No action annotations registered."))
    if counts["oracles"] == 0:
        findings.append(
            ValidationFinding(
                "error",
                "no_oracles",
                "No oracles registered, so Bridge-Maker cannot turn traces into bug evidence.",
            )
        )


def _check_specs(findings: list[ValidationFinding]) -> None:
    if REGISTRY.reset_hook is None:
        findings.append(
            ValidationFinding(
                "warning",
                "missing_reset",
                "No @bm.reset hook registered; episodes may not start from a clean state.",
            )
        )
    if REGISTRY.snapshot_hook is None:
        findings.append(
            ValidationFinding(
                "warning",
                "missing_snapshot",
                "No @bm.snapshot hook registered; reports will have less replay context.",
            )
        )
    for name, spec in REGISTRY.states.items():
        if spec.bounds is None and spec.role not in {"flag"}:
            findings.append(
                ValidationFinding(
                    "warning",
                    "missing_bounds",
                    f"State '{name}' has no bounds; generated observations may be poorly normalized.",
                    f"source={spec.source}",
                )
            )


def _check_state_values(state: dict[str, Any], findings: list[ValidationFinding]) -> None:
    for name, value in state.items():
        if not isinstance(value, (bool, int, float)):
            findings.append(
                ValidationFinding(
                    "error",
                    "unsupported_state_value",
                    f"State '{name}' returned {type(value).__name__}; use numeric or boolean state for the MVP env.",
                    repr(value),
                )
            )


def _check_oracles(state: dict[str, Any], findings: list[ValidationFinding]) -> list[dict[str, Any]]:
    view = StateView(state)
    hits: list[dict[str, Any]] = []
    for name, spec in REGISTRY.oracles.items():
        try:
            result = spec.fn(view)
        except Exception as exc:
            findings.append(
                ValidationFinding(
                    "error",
                    "oracle_failed",
                    f"Oracle '{name}' raised an exception.",
                    f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if not isinstance(result, bool):
            findings.append(
                ValidationFinding(
                    "warning",
                    "oracle_non_bool",
                    f"Oracle '{name}' returned {type(result).__name__}; Bridge-Maker will coerce it to bool.",
                    repr(result),
                )
            )
        if bool(result):
            hits.append({"name": name, "severity": spec.severity, "source": spec.source})
    return hits


def _run_action_smoke(
    runtime: BridgeRuntime,
    initial_state: dict[str, Any],
    steps: int,
    findings: list[ValidationFinding],
) -> list[dict[str, Any]]:
    names = list(REGISTRY.actions)
    if not names or steps <= 0:
        return []

    frames: list[dict[str, Any]] = []
    changed = False
    previous = dict(initial_state)
    for i in range(steps):
        action = names[i % len(names)]
        try:
            frame = runtime.step(action)
        except Exception as exc:
            findings.append(
                ValidationFinding(
                    "error",
                    "action_failed",
                    f"Action '{action}' raised an exception during validation.",
                    f"{type(exc).__name__}: {exc}",
                )
            )
            break

        if frame.state != previous:
            changed = True
        previous = dict(frame.state)
        frames.append(
            {
                "step": i + 1,
                "action": action,
                "state": frame.state,
                "oracles": frame.oracles,
            }
        )

    if frames and not changed:
        findings.append(
            ValidationFinding(
                "warning",
                "actions_did_not_change_state",
                "Validation actions ran, but sampled state did not change.",
                "This can be valid for menu actions, but early QA value is higher when at least one state changes.",
            )
        )
    return frames


def _write_report(report: ValidationReport, out_dir: str | Path | None) -> None:
    if out_dir is None:
        return
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    (out / "validation_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (out / "validation_report.md").write_text(_render_markdown(report), encoding="utf-8")


def _render_markdown(report: ValidationReport) -> str:
    lines = [
        "# Bridge-Maker Validation Report",
        "",
        f"- Adapter: `{report.adapter}`",
        f"- Status: **{report.status}**",
        f"- States: {report.counts['states']}",
        f"- Actions: {report.counts['actions']}",
        f"- Oracles: {report.counts['oracles']}",
        f"- Smoke steps: {len(report.action_steps)}",
        "",
        "## Findings",
        "",
    ]
    if report.findings:
        for f in report.findings:
            detail = f" — {f.detail}" if f.detail else ""
            lines.append(f"- **{f.severity.upper()}** `{f.code}`: {f.message}{detail}")
    else:
        lines.append("- No issues found.")
    lines.extend(["", "## Sample State", "", "```json", json.dumps(report.sample_state, indent=2), "```", ""])
    return "\n".join(lines)

