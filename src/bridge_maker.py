from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.sdk.env import SDKGymEnv
from src.sdk.export import export_contract
from src.sdk.generator import generate_sdk_env
from src.sdk.loader import load_adapter
from src.sdk.report import build_report
from src.sdk.scout import write_suggestions


def _cmd_suggest(args: argparse.Namespace) -> None:
    json_path, md_path = write_suggestions(args.repo, args.out)
    print(f"[BridgeMaker] suggestions -> {json_path}")
    print(f"[BridgeMaker] suggestions -> {md_path}")


def _cmd_export(args: argparse.Namespace) -> None:
    paths = export_contract(
        args.adapter,
        args.out,
        game_name=args.game_name,
        trace_actions=args.trace_actions,
    )
    for key, path in paths.items():
        print(f"[BridgeMaker] {key} -> {path}")


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

    p = sub.add_parser("suggest", help="Scan Python code and suggest Bridge-Maker annotations")
    p.add_argument("--repo", default=".", help="Repository or folder to scan")
    p.add_argument("--out", default="annotation_suggestions", help="Output base path without suffix")
    p.set_defaults(func=_cmd_suggest)

    p = sub.add_parser("export", help="Load an adapter and export Bridge-Maker contract files")
    p.add_argument("--adapter", required=True, help="Python adapter module path")
    p.add_argument("--out", required=True, help="Output directory")
    p.add_argument("--game-name", default=None, help="Game name stored in state_map.json")
    p.add_argument("--trace-actions", type=int, default=12, help="Number of cyclic actions recorded into trace.jsonl")
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
