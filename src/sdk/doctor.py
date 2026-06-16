from __future__ import annotations

import importlib
import json
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class DoctorReport:
    status: str
    python: str
    platform: str
    package_version: str | None
    checks: list[DoctorCheck]
    optional: dict[str, list[DoctorCheck]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CORE_IMPORTS = {
    "bridge_maker": "bridge_maker",
    "gymnasium": "gymnasium",
    "numpy": "numpy",
    "pydantic": "pydantic",
}

OPTIONAL_IMPORTS = {
    "training": {
        "stable_baselines3": "stable_baselines3",
        "ray": "ray",
    },
    "greybox": {
        "pymem": "pymem",
        "pydirectinput": "pydirectinput",
        "groq": "groq",
        "mcp": "mcp",
        "dxcam": "dxcam",
        "Pillow": "PIL",
        "pywin32": "win32gui",
    },
    "mlops": {
        "wandb": "wandb",
        "modal": "modal",
        "azure-storage-blob": "azure.storage.blob",
    },
    "noita": {
        "websockets": "websockets",
    },
}


def run_doctor(out_dir: str | Path | None = None) -> DoctorReport:
    checks = [
        _python_check(),
        _console_script_check(),
        *_import_checks(CORE_IMPORTS, required=True),
    ]
    optional = {
        group: _import_checks(imports, required=False)
        for group, imports in OPTIONAL_IMPORTS.items()
    }
    status = "ok" if all(c.status == "ok" for c in checks) else "needs_work"
    report = DoctorReport(
        status=status,
        python=sys.version.split()[0],
        platform=platform.platform(),
        package_version=_package_version(),
        checks=checks,
        optional=optional,
    )
    _write_report(report, out_dir)
    return report


def _python_check() -> DoctorCheck:
    version = sys.version_info
    if version >= (3, 10):
        return DoctorCheck("python_version", "ok", f"{version.major}.{version.minor}.{version.micro}")
    return DoctorCheck(
        "python_version",
        "error",
        f"{version.major}.{version.minor}.{version.micro}; Bridge-Maker requires Python >=3.10",
    )


def _console_script_check() -> DoctorCheck:
    path = shutil.which("bridge-maker")
    if path:
        return DoctorCheck("console_script", "ok", path)
    return DoctorCheck(
        "console_script",
        "warning",
        "bridge-maker command not found on PATH; python -m bridge_maker may still work.",
    )


def _import_checks(imports: dict[str, str], *, required: bool) -> list[DoctorCheck]:
    checks = []
    for label, module in imports.items():
        try:
            importlib.import_module(module)
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    label,
                    "error" if required else "missing",
                    f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            checks.append(DoctorCheck(label, "ok", module))
    return checks


def _package_version() -> str | None:
    try:
        return metadata.version("bridge-maker")
    except metadata.PackageNotFoundError:
        return None


def _write_report(report: DoctorReport, out_dir: str | Path | None) -> None:
    if out_dir is None:
        return
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "doctor_report.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    (out / "doctor_report.md").write_text(_render_markdown(report), encoding="utf-8")


def _render_markdown(report: DoctorReport) -> str:
    lines = [
        "# Bridge-Maker Doctor Report",
        "",
        f"- Status: **{report.status}**",
        f"- Python: `{report.python}`",
        f"- Platform: `{report.platform}`",
        f"- Package version: `{report.package_version or 'not installed as package'}`",
        "",
        "## Core checks",
        "",
    ]
    for check in report.checks:
        lines.append(f"- **{check.status.upper()}** `{check.name}`: {check.detail}")
    lines.extend(["", "## Optional extras", ""])
    for group, checks in report.optional.items():
        lines.append(f"### {group}")
        for check in checks:
            lines.append(f"- **{check.status.upper()}** `{check.name}`: {check.detail}")
        lines.append("")
    return "\n".join(lines)

