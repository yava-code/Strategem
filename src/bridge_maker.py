from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.sdk.ci import write_github_actions_workflow
from src.sdk.env import SDKGymEnv
from src.sdk.doctor import run_doctor
from src.sdk.export import export_contract
from src.sdk.generator import generate_sdk_env
from src.sdk.loader import load_adapter
from src.sdk.pipeline import run_basic_qa
from src.sdk.report import build_report
from src.sdk.scaffold import write_starter_project
from src.sdk.scout import write_suggestions
from src.sdk.validation import validate_adapter


def _cmd_init(args: argparse.Namespace) -> None:
    paths = write_starter_project(args.out, game_name=args.game_name, force=args.force)
    adapter = str(paths["adapter"])
    slug = _slug(args.game_name)
    run_dir = f"runs/{slug}"
    validation_dir = f"runs/{slug}_validation"
    print(f"[BridgeMaker] adapter -> {paths['adapter']}")
    print(f"[BridgeMaker] guide -> {paths['guide']}")
    print("[BridgeMaker] next:")
    print(f"  bridge-maker smoke --adapter \"{adapter}\" --steps 12")
    print(f"  bridge-maker validate --adapter \"{adapter}\" --out {validation_dir}")
    print(f"  bridge-maker run --adapter \"{adapter}\" --out {run_dir} --game-name \"{args.game_name}\"")


def _cmd_doctor(args: argparse.Namespace) -> None:
    report = run_doctor(args.out)
    print(f"[BridgeMaker] doctor status -> {report.status}")
    print(f"[BridgeMaker] python -> {report.python}")
    print(f"[BridgeMaker] package -> {report.package_version or 'not installed as package'}")
    for check in report.checks:
        print(f"[BridgeMaker] {check.status}: {check.name}: {check.detail}")
    for group, checks in report.optional.items():
        installed = sum(1 for check in checks if check.status == "ok")
        print(f"[BridgeMaker] optional {group} -> {installed}/{len(checks)} installed")
    if args.out:
        print(f"[BridgeMaker] doctor report -> {Path(args.out).resolve() / 'doctor_report.md'}")
    if report.status != "ok" and not args.no_fail:
        raise SystemExit(1)


def _cmd_init_ci(args: argparse.Namespace) -> None:
    path = write_github_actions_workflow(
        args.out,
        adapter=args.adapter,
        run_dir=args.run_dir,
        python_version=args.python_version,
        trace_actions=args.trace_actions,
        trace_strategy=args.trace_strategy,
        seed=args.seed,
        fail_on_bug=not args.no_fail_on_bug,
        force=args.force,
    )
    print(f"[BridgeMaker] github actions workflow -> {path}")
    print("[BridgeMaker] next:")
    print(f"  git add {path}")
    print("  git commit -m \"Add Bridge-Maker QA workflow\"")


def _cmd_suggest(args: argparse.Namespace) -> None:
    json_path, md_path = write_suggestions(args.repo, args.out)
    print(f"[BridgeMaker] suggestions -> {json_path}")
    print(f"[BridgeMaker] suggestions -> {md_path}")


def _slug(name: str) -> str:
    chars = [c.lower() if c.isalnum() else "_" for c in name]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "game"


def _cmd_export(args: argparse.Namespace) -> None:
    paths = export_contract(
        args.adapter,
        args.out,
        game_name=args.game_name,
        trace_actions=args.trace_actions,
        trace_strategy=args.trace_strategy,
        trace_seed=args.seed,
    )
    for key, path in paths.items():
        print(f"[BridgeMaker] {key} -> {path}")


def _cmd_validate(args: argparse.Namespace) -> None:
    report = validate_adapter(args.adapter, steps=args.steps, out_dir=args.out)
    print(f"[BridgeMaker] validation status -> {report.status}")
    print(
        "[BridgeMaker] contract -> "
        f"{report.counts['states']} states, {report.counts['actions']} actions, "
        f"{report.counts['oracles']} oracles"
    )
    for finding in report.findings:
        detail = f" ({finding.detail})" if finding.detail else ""
        print(f"[BridgeMaker] {finding.severity}: {finding.code}: {finding.message}{detail}")
    if args.out:
        print(f"[BridgeMaker] validation report -> {Path(args.out).resolve() / 'validation_report.md'}")
    if report.errors and not args.no_fail:
        raise SystemExit(1)


def _cmd_run(args: argparse.Namespace) -> None:
    result = run_basic_qa(
        args.adapter,
        args.out,
        game_name=args.game_name,
        validate_steps=args.validate_steps,
        trace_actions=args.trace_actions,
        trace_strategy=args.trace_strategy,
        trace_seed=args.seed,
        continue_on_validation_errors=args.continue_on_validation_errors,
    )
    print(f"[BridgeMaker] run status -> {result.status}")
    print(
        "[BridgeMaker] contract -> "
        f"{result.validation.counts['states']} states, {result.validation.counts['actions']} actions, "
        f"{result.validation.counts['oracles']} oracles"
    )
    for finding in result.validation.findings:
        detail = f" ({finding.detail})" if finding.detail else ""
        print(f"[BridgeMaker] {finding.severity}: {finding.code}: {finding.message}{detail}")
    for key, path in result.paths.items():
        print(f"[BridgeMaker] {key} -> {path}")
    if result.status == "validation_failed":
        raise SystemExit(1)
    if args.fail_on_bug and result.bug_found:
        raise SystemExit(2)


def _cmd_generate(args: argparse.Namespace) -> None:
    out = generate_sdk_env(args.contract, args.out)
    print(f"[BridgeMaker] sdk env -> {out}")


def _cmd_report(args: argparse.Namespace) -> None:
    paths = build_report(args.contract, args.out)
    for key, path in paths.items():
        print(f"[BridgeMaker] {key} -> {path}")


def _cmd_smoke(args: argparse.Namespace) -> None:
    load_adapter(args.adapter)
    env = SDKGymEnv(max_steps=args.steps + 5)
    obs, info = env.reset()
    print(f"[BridgeMaker] reset obs_shape={tuple(obs.shape)} state={json.dumps(info['state'])}")
    for i in range(args.steps):
        action = i % env.action_space.n
        obs, reward, terminated, truncated, info = env.step(action)
        print(
            f"[BridgeMaker] step={i + 1:02d} action={info.get('action')} "
            f"reward={reward:.3f} terminated={terminated} truncated={truncated}"
        )
        if terminated or truncated:
            break


def _cmd_demo(args: argparse.Namespace) -> None:
    out = Path(args.out)
    json_path, md_path = write_suggestions(Path(args.adapter).parent, out / "annotation_suggestions")
    print(f"[BridgeMaker] suggestions -> {json_path}")
    print(f"[BridgeMaker] suggestions -> {md_path}")
    paths = export_contract(
        args.adapter,
        out,
        game_name=args.game_name,
        trace_actions=args.trace_actions,
    )
    env_path = generate_sdk_env(out)
    report_paths = build_report(out)
    print(f"[BridgeMaker] state_map -> {paths['state_map']}")
    print(f"[BridgeMaker] trace -> {paths['trace']}")
    print(f"[BridgeMaker] sdk env -> {env_path}")
    print(f"[BridgeMaker] report -> {report_paths['report_html']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge-Maker contract-first SDK CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="Create a working starter adapter and quickstart guide")
    p.add_argument("--out", default="bridge_maker_starter", help="Output folder for starter files")
    p.add_argument("--game-name", default="MyGame", help="Game name used in the starter guide")
    p.add_argument("--force", action="store_true", help="Overwrite existing starter files")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("doctor", help="Check Bridge-Maker installation and optional extras")
    p.add_argument("--out", default=None, help="Optional folder for doctor_report.json/md")
    p.add_argument("--no-fail", action="store_true", help="Return exit code 0 even when core checks fail")
    p.set_defaults(func=_cmd_doctor)

    p = sub.add_parser("init-ci", help="Create a GitHub Actions workflow for Bridge-Maker QA")
    p.add_argument("--adapter", required=True, help="Adapter path used by bridge-maker run")
    p.add_argument("--out", default=".github/workflows/bridge-maker.yml", help="Workflow output path")
    p.add_argument("--run-dir", default="runs/bridge_maker_ci", help="Run artifact folder inside CI")
    p.add_argument("--python-version", default="3.12", help="Python version for actions/setup-python")
    p.add_argument("--trace-actions", type=int, default=200, help="Number of actions in CI trace")
    p.add_argument(
        "--trace-strategy",
        choices=("burst", "cycle", "random"),
        default="random",
        help="Trace strategy used by the CI workflow",
    )
    p.add_argument("--seed", type=int, default=42, help="Seed for CI random trace")
    p.add_argument("--no-fail-on-bug", action="store_true", help="Do not fail CI when oracle hits are found")
    p.add_argument("--force", action="store_true", help="Overwrite existing workflow file")
    p.set_defaults(func=_cmd_init_ci)

    p = sub.add_parser("suggest", help="Scan Python code and suggest Bridge-Maker annotations")
    p.add_argument("--repo", default=".", help="Repository or folder to scan")
    p.add_argument("--out", default="annotation_suggestions", help="Output base path without suffix")
    p.set_defaults(func=_cmd_suggest)

    p = sub.add_parser("validate", help="Validate that an adapter is useful enough for Bridge-Maker QA")
    p.add_argument("--adapter", required=True, help="Python adapter module path")
    p.add_argument("--steps", type=int, default=6, help="Number of cyclic action smoke steps")
    p.add_argument("--out", default=None, help="Optional folder for validation_report.json/md")
    p.add_argument("--no-fail", action="store_true", help="Return exit code 0 even when validation finds errors")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("run", help="Validate, export, generate, and report in one command")
    p.add_argument("--adapter", required=True, help="Python adapter module path")
    p.add_argument("--out", required=True, help="Output folder for all run artifacts")
    p.add_argument("--game-name", default=None, help="Game name stored in state_map.json")
    p.add_argument("--validate-steps", type=int, default=6, help="Number of cyclic action smoke steps")
    p.add_argument("--trace-actions", type=int, default=12, help="Number of cyclic actions recorded into trace.jsonl")
    p.add_argument(
        "--trace-strategy",
        choices=("burst", "cycle", "random"),
        default="burst",
        help="Action planning strategy for trace.jsonl",
    )
    p.add_argument("--seed", type=int, default=None, help="Seed for --trace-strategy random")
    p.add_argument(
        "--continue-on-validation-errors",
        action="store_true",
        help="Write all artifacts even when validation finds contract errors",
    )
    p.add_argument(
        "--fail-on-bug",
        action="store_true",
        help="Return exit code 2 when the generated report contains oracle hits",
    )
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("export", help="Load an adapter and export Bridge-Maker contract files")
    p.add_argument("--adapter", required=True, help="Python adapter module path")
    p.add_argument("--out", required=True, help="Output directory")
    p.add_argument("--game-name", default=None, help="Game name stored in state_map.json")
    p.add_argument("--trace-actions", type=int, default=12, help="Number of cyclic actions recorded into trace.jsonl")
    p.add_argument(
        "--trace-strategy",
        choices=("burst", "cycle", "random"),
        default="burst",
        help="Action planning strategy for trace.jsonl",
    )
    p.add_argument("--seed", type=int, default=None, help="Seed for --trace-strategy random")
    p.set_defaults(func=_cmd_export)

    p = sub.add_parser("generate", help="Generate an SDK-backed Gym env wrapper from a contract folder")
    p.add_argument("--contract", required=True, help="Contract directory produced by export")
    p.add_argument("--out", default=None, help="Generated env output path")
    p.set_defaults(func=_cmd_generate)

    p = sub.add_parser("report", help="Generate JSON and HTML report from an exported contract folder")
    p.add_argument("--contract", required=True, help="Contract directory produced by export")
    p.add_argument("--out", default=None, help="Report output directory (default: contract dir)")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("smoke", help="Run a short SDK env loop against an adapter")
    p.add_argument("--adapter", required=True, help="Python adapter module path")
    p.add_argument("--steps", type=int, default=20, help="Number of env steps")
    p.set_defaults(func=_cmd_smoke)

    p = sub.add_parser("demo", help="Run suggest + export + generate + report for a grant-ready proof folder")
    p.add_argument("--adapter", default="examples/buggy_roguelike.py", help="Python adapter module path")
    p.add_argument("--out", default="runs/grant_demo", help="Demo output directory")
    p.add_argument("--game-name", default="buggy_roguelike", help="Game name stored in state_map.json")
    p.add_argument("--trace-actions", type=int, default=12, help="Number of cyclic actions recorded into trace.jsonl")
    p.set_defaults(func=_cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
