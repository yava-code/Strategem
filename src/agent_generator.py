import argparse
import ast
import json
import os
from typing import Dict, Any, List

from src.codegen_schema import GymEnvCodeSpec, ObservationChannelSpec, ActionBindingSpec

# =====================================================================
# Schema-guided Gym environment compiler.
# Flow:  state_map.json -> GymEnvCodeSpec -> rendered module -> ast check -> disk
# The spec is produced either deterministically (default, offline) or via an
# Instructor-patched LLM that is forced to emit the same Pydantic structure.
# =====================================================================

DEFAULT_VECTORS = {
    0: [0.0, 1.0],   # MOVE_UP
    1: [0.0, -1.0],  # MOVE_DOWN
    2: [-1.0, 0.0],  # MOVE_LEFT
    3: [1.0, 0.0],   # MOVE_RIGHT
    4: [0.0, 0.0],   # IDLE
}


def _mapping_expr(var_name: str, role: str) -> str:
    """Deterministic obs[i] RHS, mirroring the hand-written env normalizers."""
    k = var_name.lower()
    if role == "coordinate":
        axis = 0 if "x" in k else 1
        dim = "self.map_width" if axis == 0 else "self.map_height"
        entity = "self.player_pos" if ("player" in k or "objective" in k) else "self.agent_pos"
        return f"{entity}[{axis}] / {dim}"
    if role == "health":
        return "self.health / 100.0"
    if role == "time":
        return "self.current_step / self.max_steps"
    return "0.5"  # opaque scalar: hold at mid-range until a mapper is wired


def build_spec_from_state_map(state_map: Dict[str, Any]) -> GymEnvCodeSpec:
    """Deterministic compiler path (no network, no LLM)."""
    variables = state_map["state_variables"]
    channels: List[ObservationChannelSpec] = []
    for i, (key, info) in enumerate(variables.items()):
        role = info.get("role", "scalar")
        channels.append(ObservationChannelSpec(
            index=i, var_name=key, role=role, mapping_expr=_mapping_expr(key, role),
        ))

    bindings = state_map.get("actions", {}).get("bindings", [])
    count = state_map.get("actions", {}).get("discrete_actions_count", len(bindings) or 5)
    actions: List[ActionBindingSpec] = []
    for i in range(count):
        name = bindings[i] if i < len(bindings) else f"ACTION_{i}"
        actions.append(ActionBindingSpec(index=i, name=name, vector=DEFAULT_VECTORS.get(i, [0.0, 0.0])))

    spec = GymEnvCodeSpec(
        game_name=state_map.get("game_name", "unknown_target"),
        num_obs=len(channels),
        actions_count=count,
        channels=channels,
        actions=actions,
    )
    spec.validate_consistency()
    return spec


class InstructorCodeSynthesizer:
    """
    Structured LLM path. Patches the Gemini/OpenAI client with Instructor and
    forces it to return a GymEnvCodeSpec. Falls back to the deterministic
    builder when the package or an API key is missing.
    """
    def __init__(self, model: str = "gemini-1.5-flash"):
        self.model = model

    def synthesize(self, state_map: Dict[str, Any]) -> GymEnvCodeSpec:
        try:
            import instructor
        except ImportError:
            print("[Agent-Generator] 'instructor' not installed; using deterministic spec builder.")
            return build_spec_from_state_map(state_map)

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("[Agent-Generator] No GEMINI_API_KEY/OPENAI_API_KEY set; using deterministic builder.")
            return build_spec_from_state_map(state_map)

        prompt = (
            "You are a Gymnasium environment compiler. Given this discovered game "
            "telemetry schema, produce one observation channel per state variable and "
            "the discrete action bindings. Map coordinate roles to normalized agent/player "
            "positions, health to health/100, time to step ratio.\n\n"
            f"{json.dumps(state_map, indent=2)}"
        )
        try:
            if os.environ.get("GEMINI_API_KEY"):
                import google.generativeai as genai  # noqa: F401
                client = instructor.from_gemini(genai.GenerativeModel(self.model))
                spec = client.messages.create(
                    messages=[{"role": "user", "content": prompt}],
                    response_model=GymEnvCodeSpec,
                )
            else:
                from openai import OpenAI
                client = instructor.from_openai(OpenAI())
                spec = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    response_model=GymEnvCodeSpec,
                )
            spec.validate_consistency()
            print("[Agent-Generator] LLM returned a validated GymEnvCodeSpec.")
            return spec
        except Exception as e:
            print(f"[Agent-Generator] LLM synthesis failed ({e}); using deterministic builder.")
            return build_spec_from_state_map(state_map)


class GymEnvironmentCompiler:
    """Renders a GymEnvCodeSpec into a syntactically verified Python module."""
    def __init__(self, state_map_path: str, use_llm: bool = False):
        with open(state_map_path, "r") as f:
            self.state_map = json.load(f)
        self.use_llm = use_llm

    def _resolve_spec(self) -> GymEnvCodeSpec:
        if self.use_llm:
            return InstructorCodeSynthesizer().synthesize(self.state_map)
        return build_spec_from_state_map(self.state_map)

    def render(self, spec: GymEnvCodeSpec) -> str:
        vec_lines = "\n".join(
            f"            {a.index}: np.array([{a.vector[0]}, {a.vector[1]}]),  # {a.name}"
            for a in spec.actions
        )
        obs_lines = "\n".join(
            f"        obs[{c.index}] = {c.mapping_expr}  # {c.var_name} ({c.role})"
            for c in spec.channels
        )

        return f'''# =====================================================================
# WARNING: AUTO-GENERATED BY THE AGENT GENERATOR. DO NOT EDIT BY HAND.
# Generated from state map: {spec.game_name}
# =====================================================================

import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import Dict, Any, Tuple, Optional
from src.config import SDKConfig
from src.reward_generator import MultiObjectiveRewardGenerator
from src.logger import SDKLogger


class {spec.class_name}(gym.Env):
    """Dynamically compiled environment matching the discovered telemetry schema."""
    metadata = {{"render_modes": ["human", "rgb_array"]}}

    def __init__(self, config: SDKConfig, logger: Optional[SDKLogger] = None):
        super().__init__()
        self.config = config
        self.logger = logger

        self.map_width, self.map_height = self.config.map_size
        self.max_steps = self.config.max_steps_per_episode
        self.agent_radius = 1.0

        self.action_space = spaces.Discrete({spec.actions_count})
        self.action_vectors = {{
{vec_lines}
        }}
        self.step_speed = {spec.step_speed}

        self.observation_space = spaces.Box(
            low={spec.obs_low}, high={spec.obs_high}, shape=({spec.num_obs},), dtype=np.float32
        )

        self.reward_generator = MultiObjectiveRewardGenerator(self.config, obs_dim={spec.num_obs})

        self.agent_pos = np.array(self.config.start_pos_agent, dtype=np.float32)
        self.prev_agent_pos = np.copy(self.agent_pos)
        self.player_pos = np.array(self.config.start_pos_player, dtype=np.float32)
        self.goal_pos = np.array(self.config.goal_pos, dtype=np.float32)
        self.health = 100.0
        self.current_step = 0
        self.npc_patrol_angle = 0.0

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        super().reset(seed=seed)
        self.agent_pos = np.array(self.config.start_pos_agent, dtype=np.float32)
        self.prev_agent_pos = np.copy(self.agent_pos)
        self.player_pos = np.array(self.config.start_pos_player, dtype=np.float32)
        self.health = 100.0
        self.current_step = 0
        self.npc_patrol_angle = 0.0
        self.reward_generator.reset()
        obs = self._get_obs()
        info = {{"agent_pos": self.agent_pos.tolist(), "player_pos": self.player_pos.tolist(),
                "health": self.health, "anomaly_detected": False}}
        return obs, info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        self.current_step += 1
        self.prev_agent_pos = np.copy(self.agent_pos)
        prev_obs = self._get_obs()
        self.reward_generator.update_action_history(action)

        if self.config.mode == "npc":
            self.npc_patrol_angle += 0.04
            radius = 20.0
            center_x, center_y = self.config.start_pos_player
            self.player_pos[0] = np.clip(center_x + radius * np.cos(self.npc_patrol_angle), 0.0, self.map_width)
            self.player_pos[1] = np.clip(center_y + radius * np.sin(self.npc_patrol_angle), 0.0, self.map_height)

        movement_vec = self.action_vectors.get(action, np.array([0.0, 0.0])) * self.step_speed
        intended_pos = self.agent_pos + movement_vec

        hit_boundary = False
        hit_obstacle = False
        if intended_pos[0] < self.agent_radius or intended_pos[0] > (self.map_width - self.agent_radius):
            hit_boundary = True
            intended_pos[0] = np.clip(intended_pos[0], self.agent_radius, self.map_width - self.agent_radius)
        if intended_pos[1] < self.agent_radius or intended_pos[1] > (self.map_height - self.agent_radius):
            hit_boundary = True
            intended_pos[1] = np.clip(intended_pos[1], self.agent_radius, self.map_height - self.agent_radius)

        for obs_rect in self.config.obstacles:
            if obs_rect.get("type") == "rect":
                ox, oy, ow, oh = obs_rect["x"], obs_rect["y"], obs_rect["w"], obs_rect["h"]
                if (intended_pos[0] + self.agent_radius > ox and intended_pos[0] - self.agent_radius < ox + ow and
                        intended_pos[1] + self.agent_radius > oy and intended_pos[1] - self.agent_radius < oy + oh):
                    hit_obstacle = True
                    intended_pos = np.copy(self.agent_pos)
                    break

        if hit_obstacle and self.logger:
            self.logger.log_anomaly("WALL_CLIP", {{"coords": intended_pos.tolist()}}, self.current_step)
        if hit_boundary and self.logger:
            self.logger.log_anomaly("OUT_OF_BOUNDS", {{"coords": intended_pos.tolist()}}, self.current_step)

        self.agent_pos = intended_pos

        triggered_bug = False
        bug_info = None
        for bz in self.config.bug_zones:
            bx, by, bw, bh = bz["x"], bz["y"], bz["w"], bz["h"]
            if (bx <= self.agent_pos[0] <= bx + bw and by <= self.agent_pos[1] <= by + bh):
                triggered_bug = True
                bug_info = bz
                if self.logger:
                    self.logger.log_anomaly("BUG_ZONE_TRIGGER",
                                            {{"zone_name": bz["name"], "coords": self.agent_pos.tolist(),
                                             "code": bz.get("error_code", "BUG")}}, self.current_step)
                break

        if self.logger:
            self.logger.log_position(self.agent_pos[0], self.agent_pos[1])

        prev_health = self.health
        if hit_obstacle:
            self.health -= 5.0
        self.health = max(0.0, self.health)

        next_obs = self._get_obs()
        state_info = {{
            "agent_pos": self.agent_pos, "prev_agent_pos": self.prev_agent_pos,
            "player_pos": self.player_pos, "goal_pos": self.goal_pos,
            "health": self.health, "prev_health": prev_health,
            "hit_obstacle": hit_obstacle, "hit_boundary": hit_boundary,
            "triggered_bug": triggered_bug, "bug_zone_info": bug_info,
            "chosen_action": action, "obs": prev_obs, "next_obs": next_obs,
        }}
        reward, reward_breakdown = self.reward_generator.calculate_reward(state_info)

        terminated = self.health <= 0.0
        if np.linalg.norm(self.agent_pos - self.goal_pos) < 3.0:
            terminated = True
        truncated = self.current_step >= self.max_steps

        info = {{"agent_pos": self.agent_pos.tolist(), "player_pos": self.player_pos.tolist(),
                "health": self.health, "anomaly_detected": triggered_bug,
                "reward_breakdown": reward_breakdown}}
        return next_obs, reward, terminated, truncated, info

    def _get_obs(self) -> np.ndarray:
        obs = np.zeros(({spec.num_obs},), dtype=np.float32)
{obs_lines}
        return obs
'''

    def compile(self, output_path: str) -> None:
        spec = self._resolve_spec()
        spec.validate_consistency()
        source = self.render(spec)

        # Task 2.3: hard syntactic gate before anything touches disk.
        try:
            ast.parse(source)
        except SyntaxError as e:
            raise RuntimeError(f"Generated environment failed AST validation: {e}") from e

        with open(output_path, "w") as f:
            f.write(source)
        print(f"[Agent-Generator] AST-validated env ({spec.num_obs} obs, "
              f"{spec.actions_count} actions) written to: '{output_path}'")


def main():
    parser = argparse.ArgumentParser(description="Gymnasium Environment Code Generator Compiler")
    parser.add_argument("--state-map", default="state_map.json", help="Path to input JSON state map")
    parser.add_argument("--output", default="src/game_env_generated.py", help="Destination Python module")
    parser.add_argument("--use-llm", action="store_true",
                        help="Use Instructor + Gemini/OpenAI structured synthesis (falls back if unavailable)")
    args = parser.parse_args()

    print(f"[Agent-Generator] Loading state specification: '{args.state_map}'...")
    if not os.path.exists(args.state_map):
        raise FileNotFoundError(f"State map file not found: {args.state_map}")

    compiler = GymEnvironmentCompiler(args.state_map, use_llm=args.use_llm)
    print(f"[Agent-Generator] Compiling to Gym environment wrapper: '{args.output}'...")
    compiler.compile(args.output)
    print("[Agent-Generator] Compilation successful!")


if __name__ == "__main__":
    main()
