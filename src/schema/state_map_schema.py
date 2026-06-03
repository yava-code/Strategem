from __future__ import annotations

import enum
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, model_validator


class SemanticRole(str, enum.Enum):
    HEALTH = "health"
    COORDINATE_X = "coordinate_x"
    COORDINATE_Y = "coordinate_y"
    COORDINATE_Z = "coordinate_z"
    DEPTH = "depth"
    TIME = "time"
    THREAT = "threat"
    SCALAR = "scalar"
    FLAG = "flag"


class PointerChain(BaseModel):
    base: str           # e.g. "GameAssembly.dll+0x1A3F80" or "0x7FF800000000"
    offsets: list[int]  # dereference chain: [0x10, 0x48, 0x2C]
    verified: bool = False  # survived a process restart


class StateVariable(BaseModel):
    type: str = "float"
    min: float
    max: float
    role: SemanticRole = SemanticRole.SCALAR
    pointer_chain: Optional[PointerChain] = None
    struct_offset: Optional[int] = None  # offset within parent struct (white-box / Ghidra)
    dynamic_only: bool = False           # no stable chain; requires re-scan each session
    source: str = "discovery"            # "discovery" | "static" | "manual"

    @model_validator(mode="after")
    def must_have_access_path(self) -> "StateVariable":
        if not self.dynamic_only and self.pointer_chain is None and self.struct_offset is None:
            raise ValueError(
                "StateVariable must have pointer_chain, struct_offset, or dynamic_only=True"
            )
        return self


class ActionBinding(BaseModel):
    id: int
    name: str
    key_binding: Optional[str] = None   # e.g. "w", "space"
    entry_point: Optional[str] = None   # static address string from Ghidra


class ActionManifest(BaseModel):
    count: int
    bindings: list[str]         # simple string form for Gym env generation
    detailed: Optional[list[ActionBinding]] = None


class StateMap(BaseModel):
    game_name: str
    engine_hint: str = "unknown"
    binary: str = ""
    module_name: str = ""       # primary module (e.g. "GameAssembly.dll")
    observation_dimensions: int
    state_variables: dict[str, StateVariable]
    actions: ActionManifest

    @model_validator(mode="after")
    def obs_dim_matches(self) -> "StateMap":
        n = len(self.state_variables)
        if self.observation_dimensions != n:
            raise ValueError(
                f"observation_dimensions={self.observation_dimensions} does not match "
                f"len(state_variables)={n}"
            )
        return self

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "StateMap":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
