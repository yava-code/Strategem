from typing import Any, Dict, Optional

from src.dashboard import DashboardServer

# =====================================================================
# Phase 4: Ray/RLLib -> Web Console bridge.
# A DefaultCallbacks handler scrapes per-step coordinates, anomalies and
# per-iteration reward/curiosity stats off the rollout workers and pushes
# them into the shared dashboard telemetry store.
# Callback signatures drift between RLLib releases, so every hook is **kwargs
# tolerant and defensive.
# =====================================================================

try:
    from ray.rllib.algorithms.callbacks import DefaultCallbacks as _BaseCallbacks
except ImportError:
    class _BaseCallbacks:  # stand-in so this module imports without Ray installed
        pass


def _unwrap_env(base_env, env_index: Optional[int]):
    """Pull the concrete env instance out of RLLib's vectorized wrapper."""
    try:
        envs = base_env.get_sub_environments()
        if envs:
            return envs[env_index or 0]
    except Exception:
        pass
    return None


class DashboardBridgeCallbacks(_BaseCallbacks):
    """Streams RLLib rollout telemetry to the glassmorphic web console."""

    def on_episode_step(self, *, episode=None, base_env=None, env_index=None, **kwargs) -> None:
        env = _unwrap_env(base_env, env_index)
        if env is None:
            return
        try:
            DashboardServer.log_position(float(env.agent_pos[0]), float(env.agent_pos[1]))
            if getattr(env, "logger", None) and env.logger.anomalies:
                latest = env.logger.anomalies[-1]
                DashboardServer.log_anomaly(latest["type"], latest["details"], latest["step"])
        except Exception:
            # Never let a telemetry hiccup take down a rollout worker.
            pass

    def on_episode_end(self, *, episode=None, base_env=None, env_index=None, **kwargs) -> None:
        env = _unwrap_env(base_env, env_index)
        if env is None:
            return
        try:
            DashboardServer.update_telemetry(
                step=int(getattr(env, "current_step", 0)),
                extrinsic_reward=0.0,
                intrinsic_reward=float(getattr(env.reward_generator, "last_intrinsic_reward", 0.0)),
                loss=float(getattr(env.reward_generator, "last_icm_loss", 0.0)),
                player_pos=env.player_pos.tolist(),
                goal_pos=env.goal_pos.tolist(),
                map_size=list(env.config.map_size),
                obstacles=env.config.obstacles,
                bug_zones=env.config.bug_zones,
            )
        except Exception:
            pass

    def on_train_result(self, *, result: Dict[str, Any] = None, **kwargs) -> None:
        if not result:
            return
        try:
            runners = result.get("env_runners", result)
            reward = runners.get("episode_return_mean", runners.get("episode_reward_mean", 0.0))
            iteration = result.get("training_iteration", 0)
            # Mine RLLib's learner stats for the built-in curiosity loss if present.
            curiosity = 0.0
            learner = result.get("info", {}).get("learner", {})
            for _pid, stats in learner.items():
                if isinstance(stats, dict):
                    curiosity = stats.get("curiosity_module", {}).get("forward_loss", curiosity)
            DashboardServer.update_metrics(
                step=int(iteration),
                extrinsic_reward=float(reward),
                intrinsic_reward=float(curiosity),
                loss=float(curiosity),
            )
        except Exception:
            pass
