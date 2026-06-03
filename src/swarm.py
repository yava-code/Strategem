import argparse
import copy
import json
import os
from typing import Any, Dict, List

import numpy as np
import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import BaseCallback

from src.config import SDKConfig
from src.logger import SDKLogger
from src.orchestrator import IntegrationOrchestrator
from src.connectors.dotnet_connector import DotNetConnector
from src.live_game_env import LiveGameEnv

# =====================================================================
# QA Swarm: spawns N PPO testers, each with a distinct reward profile, against a
# live GameTransport (mock or the real CoQ bridge). Every tester explores with
# curiosity, logs anomalies, and reports to the dashboard roster. Findings are
# unioned into a single swarm report.
# =====================================================================


def _deep_set(d: Dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def _build_profile_config(base_raw: Dict[str, Any], overrides: Dict[str, Any]) -> SDKConfig:
    raw = copy.deepcopy(base_raw)
    for dotted, value in (overrides or {}).items():
        _deep_set(raw, dotted, value)
    return SDKConfig(raw_config=raw)


class SwarmDashCallback(BaseCallback):
    """Pushes one tester's live telemetry to the dashboard roster + map."""
    def __init__(self, agent_name: str, profile: str, push_freq: int = 256,
                 dashboard_active: bool = False):
        super().__init__()
        self.agent_name = agent_name
        self.profile = profile
        self.push_freq = push_freq
        self.dashboard_active = dashboard_active
        self.steps = 0

    def _on_step(self) -> bool:
        self.steps += 1
        if not self.dashboard_active or self.steps % self.push_freq != 0:
            return True
        try:
            from src.dashboard import DashboardServer
            env = self.training_env.envs[0].unwrapped
            mean_r = 0.0
            if len(self.model.ep_info_buffer) > 0:
                mean_r = float(np.mean([e["r"] for e in self.model.ep_info_buffer]))
            anomalies = len(env.logger.anomalies) if env.logger else 0
            DashboardServer.update_agent(
                name=self.agent_name, step=self.steps, extrinsic_reward=mean_r,
                intrinsic_reward=float(getattr(env.reward_generator, "last_intrinsic_reward", 0.0)),
                anomalies=anomalies, profile=self.profile,
            )
            DashboardServer.log_position(float(env.agent_pos[0]), float(env.agent_pos[1]))
            if env.logger and env.logger.anomalies:
                latest = env.logger.anomalies[-1]
                DashboardServer.log_anomaly(latest["type"], latest["details"], latest["step"])
            DashboardServer.update_telemetry(
                step=self.steps, extrinsic_reward=mean_r,
                intrinsic_reward=float(getattr(env.reward_generator, "last_intrinsic_reward", 0.0)),
                loss=0.0, player_pos=env.agent_pos.tolist(),
                goal_pos=list(env.config.goal_pos), map_size=list(env.config.map_size),
                obstacles=[], bug_zones=[],
            )
        except Exception:
            pass
        return True


def _resolve_schema(game_path: str, state_map_path: str, host: str, port: int,
                    ghidra_url: str) -> tuple:
    """Discover via the orchestrator when the game is installed; else curated CoQ."""
    if os.path.isdir(game_path):
        orch = IntegrationOrchestrator(host=host, port=port, ghidra_url=ghidra_url)
        return orch.discover(game_path, state_map_path)
    connector = DotNetConnector(host=host, port=port)
    schema = connector.discover_schema(game_path)
    with open(state_map_path, "w") as f:
        json.dump(schema, f, indent=4)
    print(f"[Swarm] Game path absent; using curated CoQ schema -> '{state_map_path}'")
    return connector, schema


def train_swarm(config_path: str, agents_limit: int, timesteps: int,
                output_dir: str, dashboard: bool) -> Dict[str, Any]:
    with open(config_path, "r") as f:
        base_raw = yaml.safe_load(f) or {}

    conn_cfg = base_raw.get("connector", {})
    game_path = conn_cfg.get("game_path", "")
    transport_cfg = conn_cfg.get("transport", {})
    host = transport_cfg.get("host", "127.0.0.1")
    port = int(transport_cfg.get("port", 50545))
    ghidra_url = conn_cfg.get("ghidra_url", "http://127.0.0.1:8080")

    os.makedirs(output_dir, exist_ok=True)
    connector, schema = _resolve_schema(game_path, os.path.join(output_dir, "state_map.json"),
                                        host, port, ghidra_url)

    profiles = base_raw.get("swarm", {}).get("agents", [{"name": "default", "overrides": {}}])
    profiles = profiles[:agents_limit] if agents_limit else profiles

    dashboard_server = None
    if dashboard:
        from src.dashboard import DashboardServer
        dashboard_server = DashboardServer(port=8000)
        dashboard_server.start()

    swarm_report: Dict[str, Any] = {"game": schema.get("game_name"), "engine": schema.get("engine"),
                                    "agents": {}, "all_anomalies": {}}

    for prof in profiles:
        name = prof.get("name", "agent")
        overrides = prof.get("overrides", {})
        print(f"\n[Swarm] === Tester '{name}' === overrides: {overrides}")
        cfg = _build_profile_config(base_raw, overrides)

        agent_dir = os.path.join(output_dir, name)
        os.makedirs(agent_dir, exist_ok=True)

        transport = connector.open_transport(game_path, schema)
        logger = SDKLogger(map_size=(cfg.map_size[0], cfg.map_size[1]), grid_res=50)
        env = LiveGameEnv(cfg, schema, transport, logger=logger, agent_name=name)

        policy = prof.get("policy", "ppo")
        if policy == "random":
            # Pure fuzzer — a legit QA strategy: uniform random actions cover a
            # bounded zone reliably where a greedy policy fixates on one fault.
            _random_rollout(env, timesteps, name, _profile_label(overrides), dashboard)
        else:
            monitor = Monitor(env, filename=os.path.join(agent_dir, f"monitor_{name}.csv"))
            model = PPO("MlpPolicy", monitor, learning_rate=cfg.learning_rate, n_steps=cfg.n_steps,
                        batch_size=cfg.batch_size, n_epochs=cfg.n_epochs, gamma=cfg.gamma,
                        ent_coef=cfg.ent_coef, verbose=0)
            cb = SwarmDashCallback(name, _profile_label(overrides), dashboard_active=dashboard)
            model.learn(total_timesteps=timesteps, callback=cb, progress_bar=False)

        # Heatmap + anomaly report per tester.
        heatmap_path = os.path.join(agent_dir, f"heatmap_{name}.png")
        logger.save_heatmap_image(filepath=heatmap_path, obstacles=[], player_pos=cfg.start_pos_player,
                                  goal_pos=cfg.goal_pos, bug_zones=[],
                                  title=f"QA Tester '{name}' Coverage (Caves of Qud)")
        report_path = os.path.join(agent_dir, f"anomaly_report_{name}.json")
        logger.save_logs(report_path)

        anomaly_types = _tally(logger.anomalies)
        swarm_report["agents"][name] = {
            "total_steps": logger.total_steps,
            "anomalies": len(logger.anomalies),
            "anomaly_types": anomaly_types,
            "heatmap": heatmap_path,
        }
        for t, c in anomaly_types.items():
            swarm_report["all_anomalies"][t] = swarm_report["all_anomalies"].get(t, 0) + c

        print(f"[Swarm] '{name}': {logger.total_steps} steps, "
              f"{len(logger.anomalies)} anomalies {anomaly_types}")
        env.close()

    report_path = os.path.join(output_dir, "swarm_report.json")
    with open(report_path, "w") as f:
        json.dump(swarm_report, f, indent=4)
    print(f"\n[Swarm] Aggregate report -> '{report_path}'")
    print(f"[Swarm] Distinct fault classes found: {list(swarm_report['all_anomalies'].keys())}")

    if dashboard_server:
        print("[Swarm] Dashboard still live at http://localhost:8000 (Ctrl+C to stop).")
    return swarm_report


def _random_rollout(env: LiveGameEnv, timesteps: int, name: str, label: str,
                    dashboard: bool) -> None:
    obs, _ = env.reset()
    for t in range(timesteps):
        obs, _r, term, trunc, _info = env.step(env.action_space.sample())
        if term or trunc:
            obs, _ = env.reset()
        if dashboard and t % 256 == 0:
            try:
                from src.dashboard import DashboardServer
                anomalies = len(env.logger.anomalies) if env.logger else 0
                DashboardServer.update_agent(name=name, step=t, extrinsic_reward=0.0,
                                             intrinsic_reward=0.0, anomalies=anomalies, profile=label)
                DashboardServer.log_position(float(env.agent_pos[0]), float(env.agent_pos[1]))
            except Exception:
                pass


def _profile_label(overrides: Dict[str, Any]) -> str:
    if not overrides:
        return "baseline"
    return ", ".join(k.split(".")[-1] for k in overrides)


def _tally(anomalies: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for a in anomalies:
        out[a["type"]] = out.get(a["type"], 0) + 1
    return out


def main():
    parser = argparse.ArgumentParser(description="The Bridge-Maker QA Swarm")
    parser.add_argument("--config", required=True, help="Swarm YAML config")
    parser.add_argument("--agents", type=int, default=0, help="Cap number of testers (0 = all)")
    parser.add_argument("--timesteps", type=int, default=6000, help="Timesteps per tester")
    parser.add_argument("--output-dir", default="output_swarm", help="Output directory")
    parser.add_argument("--dashboard", action="store_true", help="Launch live web console")
    parser.add_argument("--transport", choices=["mock", "live"], default="mock",
                        help="mock: tools.mock_coq_server | live: the CoQ QA Bridge mod (same protocol)")
    args = parser.parse_args()

    print(f"[Swarm] Transport mode: {args.transport} "
          f"(start the {'mock server' if args.transport == 'mock' else 'game with the QA Bridge mod'} first)")
    train_swarm(args.config, args.agents, args.timesteps, args.output_dir, args.dashboard)


if __name__ == "__main__":
    main()
