"""
Bridge-Maker Session Runner — single entry point for all pipeline modes.

Modes:
  discover  Run the full discovery pipeline -> state_map.json
  generate  Generate game_env_generated.py from an existing state_map.json
  train     Run Ray/RLlib + ICM on a generated environment
  full      discover -> generate -> train in sequence

Usage:
  python -m src.run_session --session configs/session.yaml --mode discover
  python -m src.run_session --session configs/session.yaml --mode full --dashboard
  python -m src.run_session --session configs/session.yaml --mode discover --dry-run
  python -m src.run_session --session configs/session.yaml --mode discover --resume
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

# Load .env if present (GROQ_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; env vars must be set manually


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bridge-Maker Session Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--session",   default="configs/session_dummy.yaml", help="Path to session YAML config (default: configs/session_dummy.yaml)")
    parser.add_argument("--mode",      choices=["discover", "generate", "train", "full"], default="discover")
    parser.add_argument("--dry-run",   action="store_true", help="Mock CE/Ghidra calls")
    parser.add_argument("--resume",    action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--dashboard", action="store_true", help="Launch dashboard alongside")
    parser.add_argument("--state-map", default=None, help="Path to existing state_map.json (for generate/train modes)")
    args = parser.parse_args()

    if args.mode in ("discover", "full"):
        _run_discover(args)
    if args.mode in ("generate", "full"):
        _run_generate(args)
    if args.mode in ("train", "full"):
        _run_train(args)


def _run_discover(args: argparse.Namespace) -> None:
    from src.orchestrator_v2 import run
    import anyio
    print(f"\n{'='*60}")
    print("PHASE: DISCOVERY")
    print(f"{'='*60}")
    final = anyio.run(run, args.session, args.dry_run, args.resume)
    if final.get("errors"):
        sys.exit(1)


def _run_generate(args: argparse.Namespace) -> None:
    print(f"\n{'='*60}")
    print("PHASE: GYM ENV GENERATION")
    print(f"{'='*60}")

    # Resolve state_map path
    state_map_path = args.state_map
    if not state_map_path:
        with open(args.session) as f:
            cfg = yaml.safe_load(f)
        game_name = Path(cfg.get("game_exe", "unknown")).stem
        state_map_path = f"state_map_{game_name}.json"

    if not Path(state_map_path).exists():
        print(f"[Generate] state_map not found: {state_map_path}", file=sys.stderr)
        print("[Generate] Run --mode discover first.", file=sys.stderr)
        sys.exit(1)

    try:
        from src.codegen.env_compiler import compile_env
        compile_env(state_map_path)
    except ImportError:
        print("[Generate] src/codegen not yet implemented — coming in Phase 3.", file=sys.stderr)
        print(f"[Generate] state_map ready at: {state_map_path}")


def _run_train(args: argparse.Namespace) -> None:
    print(f"\n{'='*60}")
    print("PHASE: RL TRAINING")
    print(f"{'='*60}")

    if args.dashboard:
        _start_dashboard()

    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "src.train_rllib",
                        "--config", "configs/rllib_curiosity.yaml"], check=True)
    except (ImportError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"[Train] Error: {exc}", file=sys.stderr)
        print("[Train] Ensure Phase 4 (RL integration) is complete.", file=sys.stderr)


def _start_dashboard() -> None:
    import threading
    try:
        from src.dashboard import DashboardServer
        srv = DashboardServer()
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        print("[Dashboard] Started at http://localhost:5000")
    except Exception as exc:
        print(f"[Dashboard] Could not start: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
