from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path


_STATE_HINTS = {
    "hp": ("hp", "health"),
    "health": ("hp", "health"),
    "life": ("hp", "health"),
    "position": ("position", "coordinate"),
    "pos": ("position", "coordinate"),
    "inventory": ("item", "scalar"),
    "gold": ("item", "scalar"),
}

_ACTION_HINTS = {
    "move": "action",
    "attack": "attack",
    "jump": "action",
    "interact": "interact",
    "use": "use_item",
    "pickup": "interact",
}

_ORACLE_HINTS = ("invalid", "bug", "softlock", "stuck", "deadlock", "out_of_bounds")


@dataclass(frozen=True)
class AnnotationSuggestion:
    file: str
    line: int
    symbol: str
    decorator: str
    confidence: float
    reason: str


def suggest_annotations(repo: str | Path) -> list[AnnotationSuggestion]:
    root = Path(repo).resolve()
    suggestions: list[AnnotationSuggestion] = []
    for path in root.rglob("*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _has_bm_decorator(node):
                continue
            name = node.name.lower()
            deco = _suggest_for_name(name)
            if deco is None:
                continue
            suggestions.append(
                AnnotationSuggestion(
                    file=str(path.relative_to(root)),
                    line=node.lineno,
                    symbol=node.name,
                    decorator=deco,
                    confidence=0.65,
                    reason=f"name contains gameplay hint: {node.name}",
                )
            )
    return suggestions


def _suggest_for_name(name: str) -> str | None:
    if any(hint in name for hint in _ORACLE_HINTS):
        return f'@bm.oracle("{name}")'
    for hint, (decorator, role) in _STATE_HINTS.items():
        if hint in name:
            if decorator == "position":
                return '@bm.position(x="x", y="y", bounds=(0, 100))'
            if decorator == "hp":
                return '@bm.hp(bounds=(0, 100))'
            if decorator == "item":
                return f'@bm.item("{hint}")'
            return f'@bm.state("{name}", role="{role}")'
    for hint, decorator in _ACTION_HINTS.items():
        if hint in name:
            if decorator == "attack":
                return f'@bm.attack("{name}")'
            if decorator == "interact":
                return f'@bm.interact("{name}")'
            if decorator == "use_item":
                return f'@bm.use_item("{name}")'
            return f'@bm.action("{name}")'
    return None


def _has_bm_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for deco in node.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            if target.value.id == "bm":
                return True
        if isinstance(target, ast.Name) and target.id == "bm":
            return True
    return False


def write_suggestions(repo: str | Path, out_base: str | Path) -> tuple[Path, Path]:
    suggestions = suggest_annotations(repo)
    base = Path(out_base)
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps([asdict(s) for s in suggestions], indent=2),
        encoding="utf-8",
    )
    rows = [
        "# Annotation Suggestions",
        "",
        "| File | Line | Symbol | Suggested decorator | Confidence |",
        "|---|---:|---|---|---:|",
    ]
    for s in suggestions:
        rows.append(
            f"| `{s.file}` | {s.line} | `{s.symbol}` | `{s.decorator}` | {s.confidence:.2f} |"
        )
    if not suggestions:
        rows.append("| - | - | - | No suggestions found | - |")
    md_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return json_path, md_path
