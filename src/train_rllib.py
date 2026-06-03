import argparse
import os
from typing import Any, Dict

from src.config import SDKConfig
from src.logger import SDKLogger

# =====================================================================
# Phase 3 brain: Ray/RLLib training engine.
# We register our Gymnasium env in Ray's registry, attach RLLib's built-in
# Curiosity (ICM) exploration, and scale rollouts across worker processes.
# RLLib is an optional heavy dep -> guarded import with an actionable message.
# =====================================================================

try:
    import ray
    from ray.rllib.algorithms.ppo import PPOConfig
    from ray.tune.registry import register_env
    RAY_AVAILABLE = True
except ImportError:
    RAY_AVAILABLE = False

ENV_ID = "bridge_maker_env"


def _make_env(env_config: Dict[str, Any]):
    """Env factory handed to Ray's registry. Each rollout worker builds its own."""
    cfg = SDKConfig(env_config["config_path"])
    logger = SDKLogger(map_size=(cfg.map_size[0], cfg.map_size[1]), grid_res=50)
    if env_config.get("generated", False):
        from src.game_env_generated import RLGameTestingEnvGenerated
        return RLGameTestingEnvGenerated(config=cfg, logger=logger)
    from src.game_env import RLGameTestingEnv
    return RLGameTestingEnv(config=cfg, logger=logger)


def register_environment() -> None:
    """Task 3.1: bind our env factory into Ray's global registry."""
    register_env(ENV_ID, _make_env)


def build_ppo_config(config_path: str, generated: bool, num_workers: int,
                     icm_cfg: Dict[str, Any]) -> "PPOConfig":
    """
    Task 3.2/3.3: PPO + built-in Curiosity exploration, scaled across workers.

    RLLib's bundled Curiosity module lives on the old API stack, so we pin it off
    the new stack when those toggles exist (they are version dependent).
    """
    sdk = SDKConfig(config_path)
    config = (
        PPOConfig()
        .environment(env=ENV_ID, env_config={"config_path": config_path, "generated": generated})
        .framework("torch")
        .training(
            lr=sdk.learning_rate,
            gamma=sdk.gamma,
            train_batch_size=sdk.n_steps,
            num_sgd_iter=sdk.n_epochs,
            entropy_coeff=sdk.ent_coef,
        )
    )

    # Worker fan-out (Task 3.3). API renamed across releases; try both.
    try:
        config = config.env_runners(num_env_runners=num_workers)
    except Exception:
        config = config.rollouts(num_rollout_workers=num_workers)

    # Pin old API stack so the built-in Curiosity exploration is honored.
    try:
        config = config.api_stack(
            enable_rl_module_and_learner=False,
            enable_env_runner_and_connector_v2=False,
        )
    except Exception:
        pass

    # Built-in ICM exploration. eta/lr/feature_dim mirror our standalone ICM.
    try:
        config = config.exploration(
            explore=True,
            exploration_config={
                "type": "Curiosity",
                "eta": icm_cfg.get("eta", 1.0),
                "lr": icm_cfg.get("learning_rate", 1e-3),
                "feature_dim": icm_cfg.get("feature_dim", 64),
                "feature_net_config": {"fcnet_hiddens": [64], "fcnet_activation": "relu"},
                "inverse_net_hiddens": [64],
                "inverse_net_activation": "relu",
                "forward_net_hiddens": [64],
                "forward_net_activation": "relu",
                "beta": icm_cfg.get("beta", 0.2),
                "sub_exploration": {"type": "StochasticSampling"},
            },
        )
    except Exception as e:
        print(f"[RLLib] Curiosity exploration not applied on this RLLib version ({e}).")

    # Stream live metrics to the web console (Phase 4).
    try:
        from src.ray_callbacks import DashboardBridgeCallbacks
        config = config.callbacks(DashboardBridgeCallbacks)
    except Exception as e:
        print(f"[RLLib] Dashboard callbacks not attached ({e}).")

    return config


def run_rllib_training(config_path: str, generated: bool, num_workers: int,
                       iterations: int, dashboard: bool) -> None:
    sdk = SDKConfig(config_path)
    icm_cfg = sdk.raw_config.get("icm", {})

    dashboard_server = None
    if dashboard:
        from src.dashboard import DashboardServer
        dashboard_server = DashboardServer(port=8000)
        dashboard_server.start()

    ray.init(ignore_reinit_error=True, include_dashboard=False)
    register_environment()
    algo = build_ppo_config(config_path, generated, num_workers, icm_cfg).build()

    print(f"[RLLib] Training '{ENV_ID}' for {iterations} iterations on {num_workers} workers...")
    try:
        for it in range(iterations):
            result = algo.train()
            reward = result.get("env_runners", {}).get("episode_return_mean",
                                                       result.get("episode_reward_mean", 0.0))
            print(f"[RLLib] Iter {it + 1}/{iterations} | mean episode return: {reward:.2f}")
    except KeyboardInterrupt:
        print("[RLLib] Training interrupted.")
    finally:
        ckpt_dir = os.path.abspath(f"output_rllib_{sdk.mode}")
        os.makedirs(ckpt_dir, exist_ok=True)
        save_path = algo.save(ckpt_dir)
        print(f"[RLLib] Checkpoint saved: {save_path}")
        algo.stop()
        ray.shutdown()
        if dashboard_server:
            dashboard_server.stop()


def main():
    parser = argparse.ArgumentParser(description="Ray/RLLib Curiosity Training Engine")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--generated-env", action="store_true", help="Use the auto-compiled env")
    parser.add_argument("--num-workers", type=int, default=2, help="Parallel rollout workers")
    parser.add_argument("--iterations", type=int, default=20, help="Number of train() iterations")
    parser.add_argument("--dashboard", action="store_true", help="Launch the live web console")
    args = parser.parse_args()

    if not RAY_AVAILABLE:
        print("[RLLib] Ray is not installed. Install with:  pip install 'ray[rllib]'")
        print("[RLLib] Until then, use the Stable-Baselines3 path:  python -m src.train --config <cfg>")
        return

    run_rllib_training(
        config_path=args.config,
        generated=args.generated_env,
        num_workers=args.num_workers,
        iterations=args.iterations,
        dashboard=args.dashboard,
    )


if __name__ == "__main__":
    main()
