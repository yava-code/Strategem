import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import Any, Dict, List, Optional, Tuple

from src.config import SDKConfig
from src.connectors.base import GameTransport, StateFrame
from src.reward_generator import MultiObjectiveRewardGenerator
from src.logger import SDKLogger

# =====================================================================
# LiveGameEnv: the real-game counterpart to game_env.py.
# It wraps a GameTransport (mock or live mod), maps the named state frame to a
# normalized observation vector via the discovered state_map, and reuses the QA
# reward generator + ICM + logger so curiosity-driven exploration and anomaly
# logging work identically to the synthetic env.
# =====================================================================


class LiveGameEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, config: SDKConfig, state_map: Dict[str, Any],
                 transport: GameTransport, logger: Optional[SDKLogger] = None,
                 agent_name: str = "agent"):
        super().__init__()
        self.config = config
        self.transport = transport
        self.logger = logger
        self.agent_name = agent_name
        self.map_width, self.map_height = self.config.map_size
        self.max_steps = self.config.max_steps_per_episode

        variables = state_map["state_variables"]
        self.var_specs: List[Tuple[str, float, float, str]] = []
        for name, info in variables.items():
            norm = info.get("normalize", {})
            lo = float(norm.get("low", info.get("min", 0.0)))
            hi = float(norm.get("high", info.get("max", 1.0)))
            if hi - lo < 1e-6:
                hi = lo + 1.0
            self.var_specs.append((name, lo, hi, info.get("role", "scalar")))

        # Coordinate channels drive the spatial visit/curiosity grid.
        coords = [i for i, s in enumerate(self.var_specs) if s[3] == "coordinate"]
        self._xi = coords[0] if len(coords) > 0 else None
        self._yi = coords[1] if len(coords) > 1 else None
        self._hi = next((i for i, s in enumerate(self.var_specs) if s[3] == "health"), None)

        num_obs = len(self.var_specs)
        self.observation_space = spaces.Box(low=0.0, high=2.0, shape=(num_obs,), dtype=np.float32)
        action_count = state_map["actions"]["discrete_actions_count"]
        self.action_space = spaces.Discrete(action_count)

        self.reward_generator = MultiObjectiveRewardGenerator(
            self.config, obs_dim=num_obs, action_dim=action_count)

        self.agent_pos = np.zeros(2, dtype=np.float32)
        self.prev_agent_pos = np.zeros(2, dtype=np.float32)
        self.health = 100.0
        self.current_step = 0
        self._connected = False
        self.last_anomaly: Optional[str] = None
        # Run-level memory of distinct faults so the bug reward fires once per new
        # fault (no farming the nearest bug); persists across episodes.
        self._seen_faults: set = set()

    def _vectorize(self, frame: StateFrame) -> np.ndarray:
        obs = np.zeros(len(self.var_specs), dtype=np.float32)
        for i, (name, lo, hi, _role) in enumerate(self.var_specs):
            raw = float(frame.obs.get(name, lo))
            obs[i] = np.clip((raw - lo) / (hi - lo), 0.0, 2.0)
        return obs

    def _raw_pos(self, frame: StateFrame) -> Tuple[float, float]:
        x = float(frame.obs.get(self.var_specs[self._xi][0], 0.0)) if self._xi is not None else 0.0
        y = float(frame.obs.get(self.var_specs[self._yi][0], 0.0)) if self._yi is not None else 0.0
        return x, y

    def _raw_health(self, frame: StateFrame) -> float:
        if self._hi is None:
            return self.health
        name, lo, hi, _ = self.var_specs[self._hi]
        # Report health on a 0-100 scale for downstream penalties.
        return np.clip((float(frame.obs.get(name, hi)) - lo) / (hi - lo), 0.0, 1.0) * 100.0

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        super().reset(seed=seed)
        if not self._connected:
            self.transport.connect()
            self._connected = True
        frame = self.transport.reset()
        self.current_step = 0
        x, y = self._raw_pos(frame)
        self.agent_pos = np.array([x, y], dtype=np.float32)
        self.prev_agent_pos = np.copy(self.agent_pos)
        self.health = self._raw_health(frame)
        self.last_anomaly = None
        self.reward_generator.reset()
        obs = self._vectorize(frame)
        return obs, {"agent_pos": self.agent_pos.tolist(), "health": self.health}

    def step(self, action: int):
        self.current_step += 1
        prev_obs = self._vectorize_current()
        self.reward_generator.update_action_history(action)

        frame = self.transport.step(action)
        next_obs = self._vectorize(frame)

        self.prev_agent_pos = np.copy(self.agent_pos)
        x, y = self._raw_pos(frame)
        self.agent_pos = np.array([x, y], dtype=np.float32)
        prev_health = self.health
        self.health = self._raw_health(frame)

        triggered = frame.anomaly is not None
        self.last_anomaly = frame.anomaly
        hit_boundary = bool(frame.info.get("hit_boundary", False))
        hit_obstacle = bool(frame.info.get("hit_obstacle", False))

        # Reward NEW faults only — found a bug once, the incentive is to find the
        # next one, not to farm the same one. Logging still records every hit.
        novel_fault = False
        if triggered:
            sig = (frame.anomaly, int(x) // 8, int(y) // 8)
            if sig not in self._seen_faults:
                self._seen_faults.add(sig)
                novel_fault = True

        if self.logger:
            self.logger.log_position(x, y)
            if triggered:
                self.logger.log_anomaly(
                    frame.anomaly,
                    {"coords": [float(x), float(y)], "turn": int(frame.obs.get("coq_turn", self.current_step))},
                    self.current_step,
                )

        state_info = {
            "agent_pos": self.agent_pos, "prev_agent_pos": self.prev_agent_pos,
            "player_pos": self.agent_pos, "goal_pos": np.array(self.config.goal_pos, dtype=np.float32),
            "health": self.health, "prev_health": prev_health,
            "hit_obstacle": hit_obstacle, "hit_boundary": hit_boundary,
            "triggered_bug": novel_fault, "bug_zone_info": {"anomaly": frame.anomaly} if triggered else None,
            "chosen_action": action, "obs": prev_obs, "next_obs": next_obs,
        }
        reward, reward_breakdown = self.reward_generator.calculate_reward(state_info)
        reward += frame.reward_hint  # engine-side signal, if any

        terminated = bool(frame.terminated) or self.health <= 0.0
        truncated = bool(frame.truncated) or self.current_step >= self.max_steps
        info = {"agent_pos": self.agent_pos.tolist(), "health": self.health,
                "anomaly_detected": triggered, "anomaly": frame.anomaly,
                "reward_breakdown": reward_breakdown}
        return next_obs, reward, terminated, truncated, info

    def _vectorize_current(self) -> np.ndarray:
        # Re-derive the pre-step observation from cached raw state for the ICM.
        obs = np.zeros(len(self.var_specs), dtype=np.float32)
        if self._xi is not None:
            name, lo, hi, _ = self.var_specs[self._xi]
            obs[self._xi] = np.clip((self.agent_pos[0] - lo) / (hi - lo), 0.0, 2.0)
        if self._yi is not None:
            name, lo, hi, _ = self.var_specs[self._yi]
            obs[self._yi] = np.clip((self.agent_pos[1] - lo) / (hi - lo), 0.0, 2.0)
        if self._hi is not None:
            name, lo, hi, _ = self.var_specs[self._hi]
            obs[self._hi] = np.clip((self.health / 100.0), 0.0, 2.0)
        return obs

    def close(self):
        if self._connected:
            self.transport.close()
            self._connected = False
