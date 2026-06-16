from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_trace(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_report(contract_dir: str | Path, out_dir: str | Path | None = None) -> dict[str, Path]:
    root = Path(contract_dir).resolve()
    out = Path(out_dir).resolve() if out_dir else root
    out.mkdir(parents=True, exist_ok=True)

    state_map = _load_json(root / "state_map.json")
    action_map = _load_json(root / "action_map.json")
    oracle_map = _load_json(root / "oracle_map.json")
    trace = _load_trace(root / "trace.jsonl")

    oracle_hits = [
        {"frame": i, **hit, "state": frame.get("state", {}), "action": frame.get("action")}
        for i, frame in enumerate(trace)
        for hit in frame.get("oracles", [])
    ]
    actions = [frame.get("action") for frame in trace if frame.get("action")]
    action_counts = Counter(actions)
    summary = {
        "game_name": state_map.get("game_name", "unknown"),
        "state_fields": len(state_map.get("state_variables", {})),
        "actions": len(action_map.get("actions", [])),
        "oracles": len(oracle_map.get("oracles", [])),
        "trace_frames": len(trace),
        "oracle_hits": len(oracle_hits),
        "unique_actions_seen": len(action_counts),
        "status": "bug_found" if oracle_hits else "clean_trace",
    }

    report_json = out / "report.json"
    report_html = out / "report.html"
    report_json.write_text(
        json.dumps(
            {
                "summary": summary,
                "oracle_hits": oracle_hits,
                "action_counts": dict(action_counts),
                "state_fields": state_map.get("state_variables", {}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report_html.write_text(_render_html(summary, oracle_hits, action_counts, state_map), encoding="utf-8")
    return {"report_json": report_json, "report_html": report_html}


def _render_html(
    summary: dict[str, Any],
    oracle_hits: list[dict[str, Any]],
    action_counts: Counter,
    state_map: dict[str, Any],
) -> str:
    cards = "".join(
        f"<div class='card'><div class='label'>{html.escape(k.replace('_', ' ').title())}</div>"
        f"<div class='value'>{html.escape(str(v))}</div></div>"
        for k, v in summary.items()
    )
    fields = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(str(spec.get('role')))}</td>"
        f"<td>{html.escape(str(spec.get('min')))}..{html.escape(str(spec.get('max')))}</td>"
        f"<td>{html.escape(str(spec.get('source_ref') or spec.get('source')))}</td></tr>"
        for name, spec in state_map.get("state_variables", {}).items()
    )
    hits = "".join(
        f"<div class='hit'><b>{html.escape(hit['name'])}</b> after "
        f"<code>{html.escape(str(hit.get('action')))}</code>"
        f"<pre>{html.escape(json.dumps(hit.get('state', {}), indent=2))}</pre></div>"
        for hit in oracle_hits
    ) or "<p class='muted'>No oracle hits in this trace.</p>"
    bars = "".join(
        f"<div class='bar'><span>{html.escape(str(action))}</span>"
        f"<strong style='width:{min(count * 34, 240)}px'>{count}</strong></div>"
        for action, count in action_counts.items()
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Bridge-Maker MVP Report</title>
  <style>
    body {{ margin:0; font-family: Aptos, Segoe UI, Arial, sans-serif; background:#0b1020; color:#edf3ff; }}
    main {{ max-width:1120px; margin:0 auto; padding:42px 28px; }}
    h1 {{ font-size:44px; margin:0 0 6px; }}
    h2 {{ margin-top:34px; }}
    .sub {{ color:#9fb3d8; font-size:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin:28px 0; }}
    .card,.panel,.hit {{ background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.14); border-radius:14px; padding:16px; box-shadow:0 18px 45px rgba(0,0,0,.22); }}
    .label {{ color:#9fb3d8; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    .value {{ font-size:26px; font-weight:700; margin-top:6px; }}
    table {{ width:100%; border-collapse:collapse; }}
    td,th {{ border-bottom:1px solid rgba(255,255,255,.12); padding:10px; text-align:left; }}
    code,pre {{ background:rgba(0,0,0,.28); border-radius:8px; color:#d8e7ff; }}
    pre {{ padding:12px; overflow:auto; }}
    .bar {{ display:flex; align-items:center; gap:12px; margin:8px 0; }}
    .bar span {{ width:150px; color:#b8c7e7; }}
    .bar strong {{ display:inline-block; min-width:24px; padding:5px 8px; border-radius:8px; background:#62e6ac; color:#07111d; }}
    .muted {{ color:#9fb3d8; }}
  </style>
</head>
<body>
<main>
  <h1>Bridge-Maker MVP Report</h1>
  <div class="sub">Contract-first automated game QA: annotations -> semantic contract -> trace -> bug evidence.</div>
  <section class="grid">{cards}</section>
  <section class="panel"><h2>Action Coverage</h2>{bars or "<p class='muted'>No actions recorded.</p>"}</section>
  <section><h2>Oracle Findings</h2>{hits}</section>
  <section class="panel"><h2>Exported State Contract</h2><table><thead><tr><th>Field</th><th>Role</th><th>Bounds</th><th>Source</th></tr></thead><tbody>{fields}</tbody></table></section>
</main>
</body>
</html>"""
