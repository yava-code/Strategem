import numpy as np
from typing import Dict, Any, List, Tuple
from src.config import SDKConfig

class MultiObjectiveRewardGenerator:
    def __init__(self, config: SDKConfig, grid_res: int = 50, obs_dim: int = 8, action_dim: int = 5):
        self.config = config
        self.mode = config.mode
        self.weights = config.get_reward_weights()
        self.grid_res = grid_res
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        # QA coverage: keep the novelty map across episodes so the agent is pushed
        # toward genuinely unseen cells over the whole run, not just within a life.
        self.persist_exploration = config.raw_config.get("env", {}).get("persist_exploration", False)
        
        # Local matrix to track visits inside the reward generator (for curiosity calculation)
        self.map_width, self.map_height = config.map_size
        self.visit_counts = np.zeros((grid_res, grid_res), dtype=np.int32)
        
        # Track action history to compute repetition penalty
        self.action_history: List[int] = []
        self.history_max_len = 10
        
        # Telemetry metrics for dashboard tracking
        self.last_icm_loss = 0.0
        self.last_intrinsic_reward = 0.0

    def reset(self):
        """Reset state tracking components for a new episode."""
        if not self.persist_exploration:
            self.visit_counts.fill(0)
        self.action_history.clear()
        # Note: We do not reset the ICM neural network weights between episodes 
        # so that curiosity memory spans across the entire training run.

    def update_action_history(self, action: int):
        """Append to historical queue, keeping length capped."""
        self.action_history.append(action)
        if len(self.action_history) > self.history_max_len:
            self.action_history.pop(0)

    def calculate_reward(self, state_info: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        """
        Evaluate and return the multi-objective reward based on active mode.
        Returns a tuple of (total_reward, reward_components_dictionary).
        """
        if self.mode == "qa":
            total, components = self._calculate_qa_reward(state_info)
        else:
            total, components = self._calculate_npc_reward(state_info)
            
        # 3. Integrate Intrinsic Curiosity Module (ICM) if enabled in config
        icm_cfg = self.config.raw_config.get("icm", {})
        if icm_cfg.get("enabled", False):
            if not hasattr(self, "icm"):
                from src.intrinsic_curiosity import IntrinsicCuriosityModule
                self.icm = IntrinsicCuriosityModule(
                    obs_dim=self.obs_dim,
                    action_dim=self.action_dim,
                    feature_dim=icm_cfg.get("feature_dim", 16),
                    eta=icm_cfg.get("eta", 10.0),
                    beta=icm_cfg.get("beta", 0.2),
                    lr=icm_cfg.get("learning_rate", 1e-3)
                )
            
            obs = state_info.get("obs")
            next_obs = state_info.get("next_obs")
            act = state_info.get("chosen_action")
            
            if obs is not None and next_obs is not None and act is not None:
                # Compute prediction error curiosity reward
                int_reward = self.icm.compute_intrinsic_reward(obs, next_obs, act)
                
                # Backpropagate and update the ICM network weights
                f_loss, inv_loss = self.icm.update_icm(obs, next_obs, act)
                
                # Update metrics
                self.last_icm_loss = f_loss + inv_loss
                self.last_intrinsic_reward = int_reward
                
                # Combine extrinsic and intrinsic rewards
                total += int_reward
                components["intrinsic_curiosity"] = int_reward

        return total, components

    def _calculate_qa_reward(self, state: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        """
        Reward calculations for QA mode (Bug & Exploit Hunting, State Curiosity).
        Objectives:
          1. Novelty/Curiosity: Reward exploration of unvisited grid squares.
          2. Exploit Hunt: Reward entering hidden bug zones.
          3. Movement dynamics: Reward covering distance.
          4. Boundary/Collision: Penalize hitting walls/bounds.
        """
        components = {}
        total = 0.0

        # 1. State Curiosity (Exploration Bonus)
        x, y = state["agent_pos"]
        clamped_x = max(0.0, min(x, self.map_width - 1e-5))
        clamped_y = max(0.0, min(y, self.map_height - 1e-5))
        grid_x = int((clamped_x / self.map_width) * self.grid_res)
        grid_y = int((clamped_y / self.map_height) * self.grid_res)
        
        # Get count before incrementing
        prev_visits = self.visit_counts[grid_y, grid_x]
        self.visit_counts[grid_y, grid_x] += 1
        
        # Curiosity reward is higher for first-time visits and drops off for subsequent visits
        if prev_visits == 0:
            exploration_bonus = 1.0
        else:
            exploration_bonus = 1.0 / np.sqrt(prev_visits + 1)
            
        w_explore = self.weights.get("exploration_weight", 0.0)
        components["exploration"] = w_explore * exploration_bonus
        total += components["exploration"]

        # 2. Bug Found Reward
        w_bug = self.weights.get("bug_found_reward", 0.0)
        if state.get("triggered_bug", False):
            components["bug_found"] = w_bug
        else:
            components["bug_found"] = 0.0
        total += components["bug_found"]

        # 3. Movement Delta Reward (incentivize agent to keep moving, penalize static states)
        prev_x, prev_y = state["prev_agent_pos"]
        dist_moved = np.sqrt((x - prev_x)**2 + (y - prev_y)**2)
        w_mvmt = self.weights.get("movement_delta_reward", 0.0)
        components["movement_delta"] = w_mvmt * dist_moved
        total += components["movement_delta"]

        # 4. Out of bounds & Obstacle penalties
        w_oob = self.weights.get("out_of_bounds_penalty", 0.0)
        if state.get("hit_boundary", False):
            components["out_of_bounds"] = w_oob
        else:
            components["out_of_bounds"] = 0.0
        total += components["out_of_bounds"]

        w_col = self.weights.get("collision_penalty", 0.0)
        if state.get("hit_obstacle", False):
            components["collision"] = w_col
        else:
            components["collision"] = 0.0
        total += components["collision"]

        # 5. Time step penalty (keep agent moving efficiently)
        w_step = self.weights.get("step_penalty", 0.0)
        components["step_penalty"] = w_step
        total += components["step_penalty"]

        return total, components

    def _calculate_npc_reward(self, state: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        """
        Reward calculations for Smart NPC Mode.
        Objectives:
          1. Engage Player: Maintain a target distance to the player (flow state).
          2. Survival: Earn points for staying alive.
          3. Obstacle Avoidance: Avoid wall collisions.
          4. Action Variety: Penalize highly repetitive actions (jittering/spinning).
        """
        components = {}
        total = 0.0

        # 1. Target Distance Maintenance (engagement / combat radius)
        agent_pos = np.array(state["agent_pos"])
        player_pos = np.array(state["player_pos"])
        dist_to_player = np.linalg.norm(agent_pos - player_pos)
        
        target_dist = self.weights.get("target_distance", 15.0)
        tolerance = self.weights.get("distance_tolerance", 5.0)
        w_dist = self.weights.get("distance_reward_weight", 0.0)

        # Distance reward is maximum when distance equals target_dist, and falls off quadratically or linearly
        diff = abs(dist_to_player - target_dist)
        if diff <= tolerance:
            # Optimal zone: high positive reward
            dist_reward = 1.0 - (diff / tolerance)
        else:
            # Suboptimal: negative penalty proportional to distance
            dist_reward = -0.5 * (diff - tolerance)
            
        components["distance_alignment"] = w_dist * dist_reward
        total += components["distance_alignment"]

        # 2. Obstacle / Bounds Penalties
        w_col = self.weights.get("collision_penalty", 0.0)
        if state.get("hit_obstacle", False):
            components["collision"] = w_col
        else:
            components["collision"] = 0.0
        total += components["collision"]

        w_oob = self.weights.get("out_of_bounds_penalty", 0.0)
        if state.get("hit_boundary", False):
            components["out_of_bounds"] = w_oob
        else:
            components["out_of_bounds"] = 0.0
        total += components["out_of_bounds"]

        # 3. Action Repetition Penalty
        # Count the frequency of the most common action in history
        w_rep = self.weights.get("repetition_penalty", 0.0)
        if len(self.action_history) > 1:
            actions, counts = np.unique(self.action_history, return_counts=True)
            max_repeat = np.max(counts)
            # Scaling penalty: 0 if repeat count is low, increases if high
            repeat_ratio = max_repeat / len(self.action_history)
            components["action_repetition"] = w_rep * (repeat_ratio ** 2)
        else:
            components["action_repetition"] = 0.0
        total += components["action_repetition"]

        # 4. Survival Reward
        w_survival = self.weights.get("survival_reward", 0.0)
        components["survival"] = w_survival
        total += components["survival"]

        return total, components
