from typing import List, Literal
from pydantic import BaseModel, Field

# =====================================================================
# Pydantic code-spec models for the schema-guided Gym compiler.
# Instructor forces the LLM to return THIS structure (not free-form text),
# so the only thing the model controls is the per-channel mapping expression.
# The surrounding env skeleton stays deterministic -> syntax stays stable.
# =====================================================================


class ObservationChannelSpec(BaseModel):
    """One slot of the observation vector and how it is filled in _get_obs."""
    index: int = Field(..., ge=0, description="Position in the observation Box vector")
    var_name: str = Field(..., description="Discovered telemetry variable name")
    role: Literal["coordinate", "health", "time", "scalar"]
    mapping_expr: str = Field(
        ...,
        description="Python RHS assigned to obs[index], e.g. 'self.agent_pos[0] / self.map_width'",
    )


class ActionBindingSpec(BaseModel):
    index: int = Field(..., ge=0)
    name: str
    vector: List[float] = Field(..., min_length=2, max_length=2)


class GymEnvCodeSpec(BaseModel):
    """Full structured spec the compiler renders into an executable Gym class."""
    class_name: str = "RLGameTestingEnvGenerated"
    game_name: str = "unknown_target"
    num_obs: int = Field(..., gt=0)
    actions_count: int = Field(..., gt=0)
    obs_low: float = 0.0
    obs_high: float = 2.0
    step_speed: float = 3.5
    channels: List[ObservationChannelSpec]
    actions: List[ActionBindingSpec]

    def validate_consistency(self) -> None:
        if len(self.channels) != self.num_obs:
            raise ValueError(f"channel count {len(self.channels)} != num_obs {self.num_obs}")
        if len(self.actions) != self.actions_count:
            raise ValueError(f"action count {len(self.actions)} != actions_count {self.actions_count}")
        seen = {c.index for c in self.channels}
        if seen != set(range(self.num_obs)):
            raise ValueError("observation channel indices are not contiguous from 0")
