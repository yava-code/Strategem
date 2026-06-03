import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import Dict, Any, Tuple, Optional
from src.config import SDKConfig
from src.reward_generator import MultiObjectiveRewardGenerator
from src.logger import SDKLogger

class RLGameTestingEnv(gym.Env):
    """
    Custom Gymnasium Environment wrapping a 2D game level simulation.
    Bridges low-level game concepts (collision, coordinates, health) into RL-friendly shapes.
    """
    metadata = {"render_modes": ["human", "rgb_array"]}

    def __init__(self, config: SDKConfig, logger: Optional[SDKLogger] = None):
        super(RLGameTestingEnv, self).__init__()
        
        self.config = config
        self.logger = logger
        
        # Pull map specs
        self.map_width, self.map_height = self.config.map_size
        self.max_steps = self.config.max_steps_per_episode
        self.agent_radius = 1.0 # Collision size

        # Define 5 discrete actions: 0=Up, 1=Down, 2=Left, 3=Right, 4=Idle
        self.action_space = spaces.Discrete(5)
        self.action_vectors = {
            0: np.array([0.0, 1.0]),  # Up
            1: np.array([0.0, -1.0]), # Down
            2: np.array([-1.0, 0.0]), # Left
            3: np.array([1.0, 0.0]),  # Right
            4: np.array([0.0, 0.0])   # Idle
        }
        self.step_speed = 3.5 # Units moved per action step

        # Define observation space:
        # [agent_x, agent_y, player_x, player_y, agent_health, dist_to_goal, dist_to_player, step_ratio]
        # Low is 0.0, High is 2.0 (for normalized variables)
        self.observation_space = spaces.Box(
            low=0.0,
            high=2.0,
            shape=(8,),
            dtype=np.float32
        )

        # Initialize core components with fixed 8 observation dimensions
        self.reward_generator = MultiObjectiveRewardGenerator(self.config, obs_dim=8)
        
        # State variables
        self.agent_pos = np.array(self.config.start_pos_agent, dtype=np.float32)
        self.prev_agent_pos = np.copy(self.agent_pos)
        self.player_pos = np.array(self.config.start_pos_player, dtype=np.float32)
        self.goal_pos = np.array(self.config.goal_pos, dtype=np.float32)
        self.health = 100.0
        self.current_step = 0
        
        # NPC movement configuration (circular patrol path)
        self.npc_patrol_angle = 0.0

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Reset environment to initial state."""
        super().reset(seed=seed)
        
        self.agent_pos = np.array(self.config.start_pos_agent, dtype=np.float32)
        self.prev_agent_pos = np.copy(self.agent_pos)
        self.player_pos = np.array(self.config.start_pos_player, dtype=np.float32)
        self.health = 100.0
        self.current_step = 0
        self.npc_patrol_angle = 0.0
        
        self.reward_generator.reset()
        
        # Return observation and info
        obs = self._get_obs()
        info = {
            "agent_pos": self.agent_pos.tolist(),
            "player_pos": self.player_pos.tolist(),
            "health": self.health,
            "anomaly_detected": False
        }
        return obs, info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """Run one step of simulation physics, bounds, bugs, and rewards."""
        self.current_step += 1
        self.prev_agent_pos = np.copy(self.agent_pos)
        
        # Capture observation BEFORE the action is applied (for Intrinsic Curiosity calculation)
        prev_obs = self._get_obs()
        
        # Update reward generator's action history
        self.reward_generator.update_action_history(action)

        # 1. Player movement simulation
        # In NPC mode, the player moves in a slow circular path to test dynamic tracking.
        # In QA mode, the player remains stationary.
        if self.config.mode == "npc":
            self.npc_patrol_angle += 0.04
            radius = 20.0
            center_x, center_y = self.config.start_pos_player
            self.player_pos[0] = center_x + radius * np.cos(self.npc_patrol_angle)
            self.player_pos[1] = center_y + radius * np.sin(self.npc_patrol_angle)
            # Clamp player to map boundary
            self.player_pos[0] = np.clip(self.player_pos[0], 0.0, self.map_width)
            self.player_pos[1] = np.clip(self.player_pos[1], 0.0, self.map_height)

        # 2. Physics & Agent Movement
        movement_vec = self.action_vectors.get(action, np.array([0.0, 0.0])) * self.step_speed
        intended_pos = self.agent_pos + movement_vec

        # 3. Collision Checks
        hit_boundary = False
        hit_obstacle = False
        
        # Boundary Collision
        if intended_pos[0] < self.agent_radius or intended_pos[0] > (self.map_width - self.agent_radius):
            hit_boundary = True
            intended_pos[0] = np.clip(intended_pos[0], self.agent_radius, self.map_width - self.agent_radius)
        if intended_pos[1] < self.agent_radius or intended_pos[1] > (self.map_height - self.agent_radius):
            hit_boundary = True
            intended_pos[1] = np.clip(intended_pos[1], self.agent_radius, self.map_height - self.agent_radius)

        # Obstacle Collision
        for obs in self.config.obstacles:
            if obs.get("type") == "rect":
                # Check bounding box intersection with agent radius padding
                ox, oy, ow, oh = obs["x"], obs["y"], obs["w"], obs["h"]
                if (intended_pos[0] + self.agent_radius > ox and intended_pos[0] - self.agent_radius < ox + ow and
                    intended_pos[1] + self.agent_radius > oy and intended_pos[1] - self.agent_radius < oy + oh):
                    hit_obstacle = True
                    # Simple push-back physics: block movement in that direction
                    intended_pos = np.copy(self.agent_pos)
                    break
            elif obs.get("type") == "circle":
                # Check circle distance intersection
                ox, oy, orad = obs["x"], obs["y"], obs["r"]
                dist = np.linalg.norm(intended_pos - np.array([ox, oy]))
                if dist < (orad + self.agent_radius):
                    hit_obstacle = True
                    intended_pos = np.copy(self.agent_pos)
                    break

        # Log wall clipping anomalies (e.g. if the agent is moving inside an obstacle despite check,
        # or hits it multiple times, simulating collision exploits)
        if hit_obstacle and self.logger:
            self.logger.log_anomaly(
                "WALL_CLIP", 
                {"coords": intended_pos.tolist(), "action": int(action)}, 
                self.current_step
            )

        if hit_boundary and self.logger:
            self.logger.log_anomaly(
                "OUT_OF_BOUNDS", 
                {"coords": intended_pos.tolist(), "action": int(action)}, 
                self.current_step
            )

        # Update final agent position
        self.agent_pos = intended_pos

        # 4. Hidden Bug Zone Checks
        triggered_bug = False
        bug_info = None
        for bz in self.config.bug_zones:
            bx, by, bw, bh = bz["x"], bz["y"], bz["w"], bz["h"]
            # Check if agent center is inside the bug zone
            if (self.agent_pos[0] >= bx and self.agent_pos[0] <= bx + bw and
                self.agent_pos[1] >= by and self.agent_pos[1] <= by + bh):
                triggered_bug = True
                bug_info = bz
                if self.logger:
                    self.logger.log_anomaly(
                        "BUG_ZONE_TRIGGER", 
                        {"zone_name": bz["name"], "coords": self.agent_pos.tolist(), "code": bz["error_code"]}, 
                        self.current_step
                    )
                break

        # 5. Log position in heatmap
        if self.logger:
            self.logger.log_position(self.agent_pos[0], self.agent_pos[1])

        # 6. Apply Health Deterioration
        prev_health = self.health
        if hit_obstacle:
            self.health -= 5.0 # Hit wall damage
        if self.config.mode == "npc":
            # In NPC mode, keep NPC alive, but if health falls too low they die
            # Deplete health slightly over time if they run out of map boundaries
            if hit_boundary:
                self.health -= 10.0
        self.health = max(0.0, self.health)

        # Assemble observations to calculate next state representation
        next_obs = self._get_obs()

        # 7. Evaluate reward
        state_info = {
            "agent_pos": self.agent_pos,
            "prev_agent_pos": self.prev_agent_pos,
            "player_pos": self.player_pos,
            "goal_pos": self.goal_pos,
            "health": self.health,
            "prev_health": prev_health,
            "hit_obstacle": hit_obstacle,
            "hit_boundary": hit_boundary,
            "triggered_bug": triggered_bug,
            "bug_zone_info": bug_info,
            "chosen_action": action,
            # Extracted state representations passed to Reward Generator for ICM updates
            "obs": prev_obs,
            "next_obs": next_obs
        }
        reward, reward_breakdown = self.reward_generator.calculate_reward(state_info)

        # 8. Check episode termination/truncation
        terminated = False
        truncated = False
        
        if self.health <= 0.0:
            terminated = True
            
        # Goal state reached: Only counts as termination in QA mode if it reaches the goal
        dist_to_goal = np.linalg.norm(self.agent_pos - self.goal_pos)
        if dist_to_goal < 3.0:
            # Reached Goal!
            terminated = True

        if self.current_step >= self.max_steps:
            truncated = True

        # Assemble observations & info
        obs = next_obs
        
        info = {
            "agent_pos": self.agent_pos.tolist(),
            "player_pos": self.player_pos.tolist(),
            "health": self.health,
            "anomaly_detected": triggered_bug or (hit_obstacle and self.config.mode == "qa"),
            "reward_breakdown": reward_breakdown
        }

        return obs, reward, terminated, truncated, info

    def _get_obs(self) -> np.ndarray:
        """Map raw state values to normalized vector observations: [0, 2] range."""
        agent_x_norm = self.agent_pos[0] / self.map_width
        agent_y_norm = self.agent_pos[1] / self.map_height
        player_x_norm = self.player_pos[0] / self.map_width
        player_y_norm = self.player_pos[1] / self.map_height
        health_norm = self.health / 100.0
        
        # Normalized distances
        dist_to_goal = np.linalg.norm(self.agent_pos - self.goal_pos)
        max_dist = np.sqrt(self.map_width**2 + self.map_height**2)
        dist_goal_norm = dist_to_goal / max_dist
        
        dist_to_player = np.linalg.norm(self.agent_pos - self.player_pos)
        dist_player_norm = dist_to_player / max_dist
        
        step_ratio = self.current_step / self.max_steps
        
        # Return array packed in bounds
        obs = np.array([
            agent_x_norm,
            agent_y_norm,
            player_x_norm,
            player_y_norm,
            health_norm,
            dist_goal_norm,
            dist_player_norm,
            step_ratio
        ], dtype=np.float32)
        
        return obs
