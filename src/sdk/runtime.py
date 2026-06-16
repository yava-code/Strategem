from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from src.sdk.specs import ContractRegistry, REGISTRY


class StateView:
    def __init__(self, values: dict[str, Any]):
        self._values = values

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)


@dataclass
class TraceFrame:
    ts: float
    action: Optional[str]
    state: dict[str, Any]
    oracles: list[dict[str, Any]]
    snapshot: Optional[dict[str, Any]] = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "ts": self.ts,
                "action": self.action,
                "state": self.state,
                "oracles": self.oracles,
                "snapshot": self.snapshot,
            },
            ensure_ascii=False,
        )


class BridgeRuntime:
    def __init__(self, registry: ContractRegistry | None = None):
        self.registry = registry or REGISTRY
        self.frames: list[TraceFrame] = []

    def reset(self) -> dict[str, Any]:
        if self.registry.reset_hook is not None:
            self.registry.reset_hook()
        return self.sample()

    def sample(self) -> dict[str, Any]:
        return {name: spec.getter() for name, spec in self.registry.states.items()}

    def invoke(self, action: str) -> Any:
        if action not in self.registry.actions:
            raise KeyError(f"Unknown action: {action}")
        return self.registry.actions[action].fn()

    def evaluate_oracles(self, state: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        values = state or self.sample()
        view = StateView(values)
        hits = []
        for name, spec in self.registry.oracles.items():
            if bool(spec.fn(view)):
                hits.append({"name": name, "severity": spec.severity, "source": spec.source})
        return hits

    def snapshot(self) -> Optional[dict[str, Any]]:
        if self.registry.snapshot_hook is None:
            return None
        return self.registry.snapshot_hook()

    def record(self, action: Optional[str] = None) -> TraceFrame:
        state = self.sample()
        frame = TraceFrame(
            ts=time.time(),
            action=action,
            state=state,
            oracles=self.evaluate_oracles(state),
            snapshot=self.snapshot(),
        )
        self.frames.append(frame)
        return frame

    def step(self, action: str) -> TraceFrame:
        self.invoke(action)
        return self.record(action)

    def run_trace(self, actions: Iterable[str], path: str | Path) -> list[TraceFrame]:
        self.frames.clear()
        self.reset()
        self.record(None)
        for action in actions:
            self.step(action)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(frame.to_json() for frame in self.frames) + "\n", encoding="utf-8")
        return list(self.frames)
