"""
Session state checkpointing — saves/loads intermediate SessionState to JSON.
Lets the pipeline resume after interruption without re-running completed nodes.

Usage:
    save_checkpoint(state, "session_checkpoint.json")
    state = load_checkpoint("session_checkpoint.json") or _default_state(cfg)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


_SKIP_IF_POPULATED = {
    "vision_scout":   "observed_deltas",
    "memory_scout":   "scan_candidates",
    "pointer_scout":  "pointer_chains",
    "struct_scout":   "raw_struct",
    "static_scout":   "static_analysis",
    "pattern_scout":  "action_manifest",
    "synthesize":     "state_map_path",
}


def save_checkpoint(state: dict, path: str = "session_checkpoint.json") -> None:
    Path(path).write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    print(f"[Checkpoint] Saved -> {path}")


def load_checkpoint(path: str = "session_checkpoint.json") -> Optional[dict]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        print(f"[Checkpoint] Loaded from {path}")
        return data
    except Exception as exc:
        print(f"[Checkpoint] Failed to load {path}: {exc}")
        return None


def node_should_skip(node_name: str, state: dict) -> bool:
    """
    Returns True if the node's output already exists in state (resume mode).
    Prevents re-running expensive MCP operations unnecessarily.
    """
    key = _SKIP_IF_POPULATED.get(node_name)
    if key is None:
        return False
    val = state.get(key)
    if val is None:
        return False
    if isinstance(val, (list, dict)):
        return len(val) > 0
    return bool(val)
