from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


StateGetter = Callable[[], Any]
ActionFn = Callable[[], Any]
OracleFn = Callable[[Any], bool]
ResetFn = Callable[[], Any]
SnapshotFn = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class StateSpec:
    name: str
    role: str = "scalar"
    getter: StateGetter = lambda: 0.0
    bounds: Optional[tuple[float, float]] = None
    dtype: str = "float"
    source: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionSpec:
    name: str
    fn: ActionFn
    key: Optional[str] = None
    cooldown: Optional[float] = None
    source: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventSpec:
    name: str
    fn: Callable[..., Any]
    source: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class OracleSpec:
    name: str
    fn: OracleFn
    severity: str = "bug"
    source: str = ""
    tags: tuple[str, ...] = ()


@dataclass
class ContractRegistry:
    states: dict[str, StateSpec] = field(default_factory=dict)
    actions: dict[str, ActionSpec] = field(default_factory=dict)
    events: dict[str, EventSpec] = field(default_factory=dict)
    oracles: dict[str, OracleSpec] = field(default_factory=dict)
    reset_hook: Optional[ResetFn] = None
    snapshot_hook: Optional[SnapshotFn] = None

    def clear(self) -> None:
        self.states.clear()
        self.actions.clear()
        self.events.clear()
        self.oracles.clear()
        self.reset_hook = None
        self.snapshot_hook = None

    def add_state(self, spec: StateSpec) -> None:
        self.states[spec.name] = spec

    def add_action(self, spec: ActionSpec) -> None:
        self.actions[spec.name] = spec

    def add_event(self, spec: EventSpec) -> None:
        self.events[spec.name] = spec

    def add_oracle(self, spec: OracleSpec) -> None:
        self.oracles[spec.name] = spec


REGISTRY = ContractRegistry()
