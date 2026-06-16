from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np

from src.sdk.runtime import BridgeRuntime
from src.sdk.specs import ContractRegistry, REGISTRY


class SDKGymEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, registry: ContractRegistry | None = None, max_steps: int = 200):
        super().__init__()
        self.registry = registry or REGISTRY
        self.runtime = BridgeRuntime(self.registry)
        self.state_specs = list(self.registry.states.values())
        self.action_specs = list(self.registry.actions.values())
        self.max_steps = max_steps
        self.steps = 0

        lows, highs = [], []
        for spec in self.state_specs:
            lo, hi = spec.bounds or (0.0, 1.0)
            lows.append(float(lo))
            highs.append(float(hi))
        self._lows = np.asarray(lows, dtype=np.float32)
        self._highs = np.asarray(highs, dtype=np.float32)

        self.observation_space = gym.spaces.Box(
            low=0.0,
            high=1.0,
            shape=(len(self.state_specs),),
            dtype=np.float32,
        )
        self.action_space = gym.spaces.Discrete(max(1, len(self.action_specs)))

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.steps = 0
        state = self.runtime.reset()
        return self._obs(state), {"state": state}

    def step(self, action: int):
        self.steps += 1
        if not self.action_specs:
            frame = self.runtime.record(None)
        else:
            idx = int(action) % len(self.action_specs)
            frame = self.runtime.step(self.action_specs[idx].name)

        terminated = any(hit["severity"] == "bug" for hit in frame.oracles)
        truncated = self.steps >= self.max_steps
        return self._obs(frame.state), 0.0, terminated, truncated, {
            "state": frame.state,
            "oracles": frame.oracles,
            "action": frame.action,
        }

    def _obs(self, state: dict[str, Any]) -> np.ndarray:
        vals = []
        for spec in self.state_specs:
            raw = state.get(spec.name, 0.0)
            if isinstance(raw, bool):
                val = 1.0 if raw else 0.0
            elif isinstance(raw, (int, float)):
                val = float(raw)
            else:
                val = 0.0
            vals.append(val)
        arr = np.asarray(vals, dtype=np.float32)
        span = np.where(self._highs - self._lows == 0.0, 1.0, self._highs - self._lows)
        return np.clip((arr - self._lows) / span, 0.0, 1.0).astype(np.float32)
