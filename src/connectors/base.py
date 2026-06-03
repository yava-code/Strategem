from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# =====================================================================
# Connector / Transport contracts.
# A Connector resolves a target into (1) a state schema (state_map.json shape)
# and (2) a live GameTransport. The transport speaks one frame contract
# regardless of whether the source is a real game socket or the mock.
# =====================================================================


@dataclass
class StateFrame:
    """One observation tick coming back from a game (mock or live)."""
    obs: Dict[str, float]
    reward_hint: float = 0.0
    terminated: bool = False
    truncated: bool = False
    anomaly: Optional[str] = None
    info: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_wire(cls, payload: Dict[str, Any]) -> "StateFrame":
        return cls(
            obs={k: float(v) for k, v in payload.get("obs", {}).items()},
            reward_hint=float(payload.get("reward_hint", 0.0)),
            terminated=bool(payload.get("terminated", False)),
            truncated=bool(payload.get("truncated", False)),
            anomaly=payload.get("anomaly"),
            info=payload.get("info", {}),
        )


class GameTransport(ABC):
    """Bidirectional channel: send an action, receive a StateFrame."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def reset(self) -> StateFrame: ...

    @abstractmethod
    def step(self, action: int) -> StateFrame: ...

    @abstractmethod
    def close(self) -> None: ...


class Connector(ABC):
    """Resolves a target game into a schema + a live transport."""

    name: str = "base"

    @abstractmethod
    def detect(self, target: str) -> bool:
        """True if this connector can handle the target path/process."""

    @abstractmethod
    def discover_schema(self, target: str) -> Dict[str, Any]:
        """Return a state_map.json-shaped dict for the target."""

    @abstractmethod
    def open_transport(self, target: str, schema: Dict[str, Any]) -> GameTransport:
        """Return a connected (or ready-to-connect) GameTransport."""
