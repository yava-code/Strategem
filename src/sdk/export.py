from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.schema.state_map_schema import (
    ActionBinding,
    ActionManifest,
    StateMap,
    StateVariable,
)
from src.sdk.loader import load_adapter
from src.sdk.runtime import BridgeRuntime
from src.sdk.specs import ContractRegistry, REGISTRY, StateSpec


def _bounds(spec: StateSpec, value: Any) -> tuple[float, float]:
    if spec.bounds is not None:
        return spec.bounds
    if isinstance(value, bool):
        return 0.0, 1.0
    if isinstance(value, (int, float)):
        val = float(value)
        if val == 0.0:
            return 0.0, 1.0
        return min(0.0, val), max(1.0, abs(val) * 2.0)
    return 0.0, 1.0


def build_state_map(
    registry: ContractRegistry | None = None,
    *,
    game_name: str = "sdk_adapter",
    sample: dict[str, Any] | None = None,
) -> StateMap:
    reg = registry or REGISTRY
    runtime = BridgeRuntime(reg)
    values = sample or runtime.sample()
    state_vars = {}

    for name, spec in reg.states.items():
        lo, hi = _bounds(spec, values.get(name))
        state_vars[name] = StateVariable(
            type=spec.dtype,
            min=lo,
            max=hi,
            role=spec.role,
            dynamic_only=True,
            source="sdk",
            source_ref=spec.source,
            initial_scan_value=float(values[name]) if isinstance(values.get(name), (int, float)) else None,
        )

    actions = [
        ActionBinding(id=i, name=spec.name, key_binding=spec.key, entry_point=spec.source)
        for i, spec in enumerate(reg.actions.values())
    ]
    return StateMap(
        game_name=game_name,
        engine_hint="sdk",
        binary="",
        module_name="sdk",
        observation_dimensions=len(state_vars),
        state_variables=state_vars,
        actions=ActionManifest(
            count=len(actions),
            bindings=[a.name for a in actions],
            detailed=actions,
        ),
    )


def action_map(registry: ContractRegistry | None = None) -> dict[str, Any]:
    reg = registry or REGISTRY
    return {
        "actions": [
            {
                "id": i,
                "name": spec.name,
                "key": spec.key,
                "cooldown": spec.cooldown,
                "source": spec.source,
                "tags": list(spec.tags),
            }
            for i, spec in enumerate(reg.actions.values())
        ]
    }


def oracle_map(registry: ContractRegistry | None = None) -> dict[str, Any]:
    reg = registry or REGISTRY
    return {
        "oracles": [
            {
                "name": spec.name,
                "severity": spec.severity,
                "source": spec.source,
                "tags": list(spec.tags),
            }
            for spec in reg.oracles.values()
        ],
        "events": [
            {"name": spec.name, "source": spec.source, "tags": list(spec.tags)}
            for spec in reg.events.values()
        ],
    }


def export_contract(
    adapter: str | Path,
    out_dir: str | Path,
    *,
    game_name: str | None = None,
    trace_actions: int = 12,
) -> dict[str, Path]:
    adapter_path = Path(adapter).resolve()
    load_adapter(adapter_path)
    runtime = BridgeRuntime()
    sample = runtime.reset()
    name = game_name or adapter_path.stem
    state_map = build_state_map(game_name=name, sample=sample)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "state_map": out / "state_map.json",
        "action_map": out / "action_map.json",
        "oracle_map": out / "oracle_map.json",
        "trace": out / "trace.jsonl",
        "manifest": out / "contract.json",
    }

    state_map.save(paths["state_map"])
    paths["action_map"].write_text(json.dumps(action_map(), indent=2), encoding="utf-8")
    paths["oracle_map"].write_text(json.dumps(oracle_map(), indent=2), encoding="utf-8")

    names = list(REGISTRY.actions)
    actions = []
    while names and len(actions) < trace_actions:
        for name in names:
            actions.extend([name, name, name])
            if len(actions) >= trace_actions:
                break
    actions = actions[:trace_actions]
    runtime.run_trace(actions, paths["trace"])
    paths["manifest"].write_text(
        json.dumps(
            {
                "adapter": str(adapter_path),
                "game_name": name,
                "state_map": str(paths["state_map"]),
                "action_map": str(paths["action_map"]),
                "oracle_map": str(paths["oracle_map"]),
                "trace": str(paths["trace"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return paths
