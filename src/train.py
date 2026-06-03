import argparse
import os
import time
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import BaseCallback

from src.config import SDKConfig
from src.logger import SDKLogger

class TrainingMetricsCallback(BaseCallback):
    """Callback to print training stats and stream metrics to the dashboard server."""
    def __init__(self, verbose: int = 0, check_freq: int = 5000, dashboard_active: bool = False):
        super(TrainingMetricsCallback, self).__init__(verbose)
        self.check_freq = check_freq
        self.step_count = 0
        self.dashboard_active = dashboard_active

    def _on_step(self) -> bool:
        self.step_count += 1
        
        # Periodic terminal logging
        if self.step_count % self.check_freq == 0:
            if len(self.model.ep_info_buffer) > 0:
                mean_reward = np.mean([ep_info['r'] for ep_info in self.model.ep_info_buffer])
                mean_length = np.mean([ep_info['l'] for ep_info in self.model.ep_info_buffer])
                print(f"[RL-SDK] Steps: {self.step_count} | Mean Ep Reward: {mean_reward:.2f} | Mean Ep Length: {mean_length:.1f}")
        
        # Real-time dashboard updates
        if self.dashboard_active:
            try:
                # Retrieve the underlying environment unwrapped
                env = self.training_env.envs[0]
                raw_env = env.unwrapped
                
                from src.dashboard import DashboardServer
                
                # Fetch extrinsic vs intrinsic rewards
                # Sum the components of the reward generator for live breakdown
                extrinsic_reward = 0.0
                if hasattr(raw_env.reward_generator, "weights"):
                    # Extrinsic reward values currently active
                    if raw_env.reward_generator.mode == "qa" and raw_env.reward_generator.config.raw_config.get("rewards", {}).get("qa", {}).get("bug_found_reward", 0.0) > 0:
                        extrinsic_reward = raw_env.reward_generator.config.raw_config["rewards"]["qa"]["bug_found_reward"]
                
                intrinsic_reward = getattr(raw_env.reward_generator, "last_intrinsic_reward", 0.0)
                loss = getattr(raw_env.reward_generator, "last_icm_loss", 0.0)
                
                # Stream coordinates
                DashboardServer.log_position(raw_env.agent_pos[0], raw_env.agent_pos[1])
                
                # Stream anomalies
                if raw_env.logger and len(raw_env.logger.anomalies) > 0:
                    latest = raw_env.logger.anomalies[-1]
                    DashboardServer.log_anomaly(
                        anomaly_type=latest["type"],
                        details=latest["details"],
                        step=self.step_count
                    )
                
                # Flush telemetry
                DashboardServer.update_telemetry(
                    step=self.step_count,
                    extrinsic_reward=extrinsic_reward,
                    intrinsic_reward=intrinsic_reward,
                    loss=loss,
                    player_pos=raw_env.player_pos.tolist(),
                    goal_pos=raw_env.goal_pos.tolist(),
                    map_size=raw_env.config.map_size,
                    obstacles=raw_env.config.obstacles,
                    bug_zones=raw_env.config.bug_zones
                )
            except Exception as e:
                # Silent fail to prevent dashboard thread glitches from crashing the ML training loop
                pass
                
        return True

def run_evaluation(env, model: PPO, num_episodes: int = 5) -> None:
    """Run trained policy to record actions, positions and anomalies."""
    print(f"\n[RL-SDK] Starting Evaluation Run ({num_episodes} episodes)...")
    for ep in range(num_episodes):
        obs, info = env.reset()
        done = False
        ep_reward = 0.0
        step_count = 0
        
        while not done:
            action, _states = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(int(action))
            ep_reward += reward
            step_count += 1
            done = terminated or truncated
            
        print(f"  - Episode {ep+1} complete. Steps: {step_count} | Total Reward: {ep_reward:.2f} | Health Remaining: {info['health']}")

def main():
    parser = argparse.ArgumentParser(description="RL-Driven Game Testing & Behavior SDK Trainer")
    parser.add_argument("--config", type=str, required=True, help="Path to the YAML configuration file")
    parser.add_argument("--timesteps", type=int, default=None, help="Override total training timesteps")
    parser.add_argument("--output-dir", type=str, default="output", help="Directory to save weights, plots, and logs")
    parser.add_argument("--dashboard", action="store_true", help="Launch the local live browser console dashboard")
    parser.add_argument("--generated-env", action="store_true", help="Use the auto-compiled Gymnasium environment wrapper")
    args = parser.parse_args()

    # Create directories
    os.makedirs(args.output_dir, exist_ok=True)

    # 1. Load Configurations
    print(f"[RL-SDK] Loading configuration from: {args.config}")
    config = SDKConfig(args.config)
    
    # Check overrides
    timesteps = args.timesteps if args.timesteps is not None else config.total_timesteps
    print(f"[RL-SDK] Mode: {config.mode.upper()}")
    print(f"[RL-SDK] Total Training Timesteps: {timesteps}")
    print(f"[RL-SDK] Map Size: {config.map_size} | Obstacles: {len(config.obstacles)} | Bug Zones: {len(config.bug_zones)}")

    # 2. Setup Logging Infrastructure
    logger = SDKLogger(map_size=(config.map_size[0], config.map_size[1]), grid_res=50)

    # 3. Import and Instantiate Environment
    if args.generated_env:
        print("[RL-SDK] Instantiating AUTO-GENERATED Environment wrapper...")
        from src.game_env_generated import RLGameTestingEnvGenerated
        raw_env = RLGameTestingEnvGenerated(config=config, logger=logger)
    else:
        print("[RL-SDK] Instantiating Standard Controlled Environment wrapper...")
        from src.game_env import RLGameTestingEnv
        raw_env = RLGameTestingEnv(config=config, logger=logger)

    monitor_env = Monitor(raw_env, filename=os.path.join(args.output_dir, f"monitor_{config.mode}.csv"))

    # 4. Optional Dashboard Web Server
    dashboard_server = None
    if args.dashboard:
        from src.dashboard import DashboardServer
        print("[RL-SDK] Starting local dashboard server on port 8000...")
        dashboard_server = DashboardServer(port=8000)
        dashboard_server.start()

    # 5. Initialize Stable-Baselines3 PPO Algorithm
    print(f"[RL-SDK] Initializing PPO agent...")
    model = PPO(
        policy="MlpPolicy",
        env=monitor_env,
        learning_rate=config.learning_rate,
        n_steps=config.n_steps,
        batch_size=config.batch_size,
        n_epochs=config.n_epochs,
        gamma=config.gamma,
        ent_coef=config.ent_coef,
        tensorboard_log=os.path.join(args.output_dir, "tb_logs"),
        verbose=0
    )

    # 6. Execute Training Loop
    print(f"[RL-SDK] Starting PPO training loop...")
    start_time = time.time()
    
    metrics_callback = TrainingMetricsCallback(
        check_freq=4000, 
        dashboard_active=args.dashboard
    )
    
    try:
        model.learn(
            total_timesteps=timesteps,
            callback=metrics_callback,
            progress_bar=True
        )
    except KeyboardInterrupt:
        print("[RL-SDK] Training interrupted by user.")
    
    training_duration = time.time() - start_time
    print(f"[RL-SDK] Training completed in {training_duration:.2f} seconds.")

    # 7. Save model weights
    weights_path = os.path.join(args.output_dir, f"ppo_model_{config.mode}.zip")
    model.save(weights_path)
    print(f"[RL-SDK] Saved trained policy to: {weights_path}")

    # 8. Evaluate Policy and Capture Detailed Diagnostics
    # We reset the logger to record evaluation-only footprint heatmap and bug hits
    eval_logger = SDKLogger(map_size=(config.map_size[0], config.map_size[1]), grid_res=50)
    raw_env.logger = eval_logger
    raw_env.reward_generator.reset()
    
    run_evaluation(raw_env, model, num_episodes=10)

    # 9. Export Plots and Reports
    heatmap_path = os.path.join(args.output_dir, f"heatmap_{config.mode}.png")
    eval_logger.save_heatmap_image(
        filepath=heatmap_path,
        obstacles=config.obstacles,
        player_pos=config.start_pos_player,
        goal_pos=config.goal_pos,
        bug_zones=config.bug_zones,
        title=f"Evaluation Agent Exploration Heatmap ({config.mode.upper()} Mode)"
    )
    print(f"[RL-SDK] Generated heatmap visualization at: {heatmap_path}")

    logs_path = os.path.join(args.output_dir, f"anomaly_report_{config.mode}.json")
    eval_logger.save_logs(logs_path)
    print(f"[RL-SDK] Saved exploit & anomaly logs to: {logs_path}")
    
    print(f"\n[RL-SDK] Evaluation Summary:")
    print(f"  - Total Actions Logged: {eval_logger.total_steps}")
    print(f"  - Bug/Vulnerability Zones Hit: {eval_logger.bug_zone_hits}")
    print(f"  - Boundary Cross Violations: {eval_logger.oob_violations}")
    print(f"  - Obstacle Collision Events: {eval_logger.wall_clips}")
    
    # Stop dashboard server if running
    if dashboard_server:
        dashboard_server.stop()
        
    print(f"[RL-SDK] SDK run complete!\n")

if __name__ == "__main__":
    main()
