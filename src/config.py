import yaml
import os
from typing import Dict, Any, List

class SDKConfig:
    def __init__(self, config_path: str = None, raw_config: Dict[str, Any] = None):
        # raw_config lets the swarm build per-agent variants in memory without
        # round-tripping through temp YAML files.
        if raw_config is not None:
            self.raw_config: Dict[str, Any] = raw_config
        else:
            if not config_path or not os.path.exists(config_path):
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            with open(config_path, 'r') as f:
                self.raw_config = yaml.safe_load(f) or {}

        # Mode validation
        self.mode: str = self.raw_config.get("mode", "qa")
        if self.mode not in ["qa", "npc"]:
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'qa' or 'npc'")

        # Environment configuration
        env_cfg = self.raw_config.get("env", {})
        self.map_size: List[float] = env_cfg.get("map_size", [100.0, 100.0])
        self.start_pos_agent: List[float] = env_cfg.get("start_pos_agent", [10.0, 10.0])
        self.start_pos_player: List[float] = env_cfg.get("start_pos_player", [80.0, 80.0])
        self.goal_pos: List[float] = env_cfg.get("goal_pos", [90.0, 90.0])
        self.max_steps_per_episode: int = env_cfg.get("max_steps_per_episode", 200)
        self.obstacles: List[Dict[str, Any]] = env_cfg.get("obstacles", [])
        self.bug_zones: List[Dict[str, Any]] = env_cfg.get("bug_zones", [])

        # Reward weights
        rewards_cfg = self.raw_config.get("rewards", {})
        self.qa_rewards: Dict[str, Any] = rewards_cfg.get("qa", {})
        self.npc_rewards: Dict[str, Any] = rewards_cfg.get("npc", {})

        # Reinforcement Learning parameters
        rl_cfg = self.raw_config.get("rl", {})
        self.algorithm: str = rl_cfg.get("algorithm", "PPO")
        self.learning_rate: float = rl_cfg.get("learning_rate", 0.0003)
        self.n_steps: int = rl_cfg.get("n_steps", 2048)
        self.batch_size: int = rl_cfg.get("batch_size", 64)
        self.n_epochs: int = rl_cfg.get("n_epochs", 10)
        self.gamma: float = rl_cfg.get("gamma", 0.99)
        self.ent_coef: float = rl_cfg.get("ent_coef", 0.01)
        self.total_timesteps: int = rl_cfg.get("total_timesteps", 40000)

    def get_reward_weights(self) -> Dict[str, Any]:
        if self.mode == "qa":
            return self.qa_rewards
        return self.npc_rewards
