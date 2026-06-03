import json
import socket
import struct
from typing import Any, Dict, Optional, Tuple

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from src.config import SDKConfig

# =====================================================================
# Phase 5: High-performance engine bridges.
# Adapter pattern: each engine wrapper (Unity ML-Agents, Godot RL, Unreal
# Learning Agents) is normalized onto the Gymnasium 5-tuple contract so the
# RLLib/SB3 trainers stay engine-agnostic. All engine SDKs are optional and
# import-guarded; the bridges raise actionable errors only on connect().
# =====================================================================


class MLAgentsGymAdaptor(gym.Env):
    """
    Wraps a Unity ML-Agents UnityEnvironment and rebases its legacy 4-tuple
    gym API onto Gymnasium's (obs, reward, terminated, truncated, info).
    """
    metadata = {"render_modes": []}

    def __init__(self, file_name: Optional[str] = None, worker_id: int = 0, no_graphics: bool = True):
        super().__init__()
        self.file_name = file_name
        self.worker_id = worker_id
        self.no_graphics = no_graphics
        self._wrapped = None
        self.observation_space: Optional[spaces.Space] = None
        self.action_space: Optional[spaces.Space] = None

    def connect(self) -> None:
        try:
            from mlagents_envs.environment import UnityEnvironment
            from mlagents_envs.envs.unity_gym_env import UnityToGymWrapper
        except ImportError as e:
            raise ImportError("Unity bridge needs 'mlagents-envs'. pip install mlagents-envs") from e

        unity_env = UnityEnvironment(file_name=self.file_name, worker_id=self.worker_id,
                                     no_graphics=self.no_graphics)
        self._wrapped = UnityToGymWrapper(unity_env, uint8_visual=False, allow_multiple_obs=False)
        self.observation_space = self._wrapped.observation_space
        self.action_space = self._wrapped.action_space

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        super().reset(seed=seed)
        obs = self._wrapped.reset()
        return np.asarray(obs, dtype=np.float32), {}

    def step(self, action):
        obs, reward, done, info = self._wrapped.step(action)
        # ML-Agents collapses termination/truncation; treat max-step as truncation.
        truncated = bool(info.get("TimeLimit.truncated", False))
        terminated = bool(done) and not truncated
        return np.asarray(obs, dtype=np.float32), float(reward), terminated, truncated, info

    def close(self):
        if self._wrapped is not None:
            self._wrapped.close()


class GodotRLGymAdaptor(gym.Env):
    """Adapts a Godot RL agents env (gRPC/IPC bridge) to the Gymnasium contract."""
    metadata = {"render_modes": []}

    def __init__(self, env_path: Optional[str] = None, port: int = 11008, show_window: bool = False):
        super().__init__()
        self.env_path = env_path
        self.port = port
        self.show_window = show_window
        self._wrapped = None
        self.observation_space: Optional[spaces.Space] = None
        self.action_space: Optional[spaces.Space] = None

    def connect(self) -> None:
        try:
            from godot_rl.core.godot_env import GodotEnv
        except ImportError as e:
            raise ImportError("Godot bridge needs 'godot-rl'. pip install godot-rl") from e

        self._wrapped = GodotEnv(env_path=self.env_path, port=self.port, show_window=self.show_window)
        self.observation_space = self._wrapped.observation_space
        self.action_space = self._wrapped.action_space

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        super().reset(seed=seed)
        obs, info = self._wrapped.reset()
        return np.asarray(obs, dtype=np.float32), info or {}

    def step(self, action):
        obs, reward, term, trunc, info = self._wrapped.step(action)
        return np.asarray(obs, dtype=np.float32), float(reward), bool(term), bool(trunc), info

    def close(self):
        if self._wrapped is not None:
            self._wrapped.close()


class UnrealLearningAgentsBridge(gym.Env):
    """
    Bridges Unreal Engine 5.4 Learning Agents over gRPC, with a length-prefixed
    JSON socket fallback (the 'Socket IPC' arm of the architecture).

    Wire contract (both transports) per step:
        request : {"cmd": "step", "action": [...]}  | {"cmd": "reset"}
        response: {"obs": [...], "reward": float, "terminated": bool, "truncated": bool, "info": {}}
    """
    metadata = {"render_modes": []}

    def __init__(self, obs_dim: int, action_dim: int, host: str = "127.0.0.1",
                 port: int = 50051, use_grpc: bool = True, timeout: float = 0.003):
        super().__init__()
        self.host = host
        self.port = port
        self.use_grpc = use_grpc
        self.timeout = timeout  # 3ms budget per the latency verification criterion
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32)
        self.action_space = spaces.Discrete(action_dim)

        self._channel = None
        self._rpc = None
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        if self.use_grpc:
            try:
                import grpc
            except ImportError:
                print("[UnrealBridge] grpcio not installed; falling back to socket IPC.")
            else:
                self._channel = grpc.insecure_channel(f"{self.host}:{self.port}")
                grpc.channel_ready_future(self._channel).result(timeout=5.0)
                # Generic stub via the low-level call API: no compiled .proto required.
                self._rpc = self._channel.unary_unary(
                    "/UnrealLearningAgents/Exchange",
                    request_serializer=lambda d: json.dumps(d).encode("utf-8"),
                    response_deserializer=lambda b: json.loads(b.decode("utf-8")),
                )
                return
        # Socket IPC transport
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self.host, self.port))
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _exchange(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._rpc is not None:
            return self._rpc(payload, timeout=max(self.timeout, 1.0))
        if self._sock is None:
            raise RuntimeError("Bridge not connected. Call connect() first.")
        body = json.dumps(payload).encode("utf-8")
        self._sock.sendall(struct.pack(">I", len(body)) + body)
        header = self._recv_exact(4)
        (length,) = struct.unpack(">I", header)
        return json.loads(self._recv_exact(length).decode("utf-8"))

    def _recv_exact(self, n: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < n:
            part = self._sock.recv(n - len(chunks))
            if not part:
                raise ConnectionError("Unreal bridge closed the connection mid-frame.")
            chunks.extend(part)
        return bytes(chunks)

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        super().reset(seed=seed)
        resp = self._exchange({"cmd": "reset"})
        return np.asarray(resp["obs"], dtype=np.float32), resp.get("info", {})

    def step(self, action):
        act = action.tolist() if isinstance(action, np.ndarray) else action
        resp = self._exchange({"cmd": "step", "action": act})
        return (
            np.asarray(resp["obs"], dtype=np.float32),
            float(resp["reward"]),
            bool(resp["terminated"]),
            bool(resp["truncated"]),
            resp.get("info", {}),
        )

    def close(self):
        if self._channel is not None:
            self._channel.close()
        if self._sock is not None:
            self._sock.close()


class EngineConfigMapper:
    """
    Task 5.3: translate our YAML reward profiles into engine-side reward configs
    so designers tune behavior on the engine they already work in.
    """
    def __init__(self, sdk_config: SDKConfig):
        self.cfg = sdk_config
        self.weights = sdk_config.get_reward_weights()

    def to_unity_mlagents(self) -> Dict[str, Any]:
        """Maps onto an ML-Agents behavior block (trainer_config.yaml style)."""
        return {
            "behaviors": {
                f"BridgeMaker_{self.cfg.mode.upper()}": {
                    "trainer_type": "ppo",
                    "hyperparameters": {
                        "learning_rate": self.cfg.learning_rate,
                        "batch_size": self.cfg.batch_size,
                        "buffer_size": self.cfg.n_steps,
                        "num_epoch": self.cfg.n_epochs,
                    },
                    "reward_signals": {
                        "extrinsic": {"gamma": self.cfg.gamma, "strength": 1.0},
                        "curiosity": {"gamma": self.cfg.gamma, "strength": 0.5,
                                      "encoding_size": 64, "learning_rate": 3e-4},
                    },
                    "max_steps": self.cfg.total_timesteps,
                    "reward_weights": dict(self.weights),
                }
            }
        }

    def to_unreal(self) -> Dict[str, Any]:
        """Maps onto a UE5 Learning Agents reward profile."""
        return {
            "AgentProfile": f"BridgeMaker_{self.cfg.mode.upper()}",
            "TrainerType": self.cfg.algorithm,
            "DiscountFactor": self.cfg.gamma,
            "RewardComponents": {k: float(v) for k, v in self.weights.items()},
            "MaxStepsPerEpisode": self.cfg.max_steps_per_episode,
        }

    def to_godot(self) -> Dict[str, Any]:
        """Maps onto a Godot RL agent sync config."""
        return {
            "env_mode": self.cfg.mode,
            "action_repeat": 1,
            "speedup": 1,
            "reward_weights": {k: float(v) for k, v in self.weights.items()},
            "rl_params": {
                "learning_rate": self.cfg.learning_rate,
                "gamma": self.cfg.gamma,
                "n_steps": self.cfg.n_steps,
            },
        }

    def export(self, engine: str) -> Dict[str, Any]:
        dispatch = {"unity": self.to_unity_mlagents, "unreal": self.to_unreal, "godot": self.to_godot}
        if engine not in dispatch:
            raise ValueError(f"Unknown engine '{engine}'. Expected one of {list(dispatch)}.")
        return dispatch[engine]()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Engine config mapper / bridge utility")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--engine", choices=["unity", "unreal", "godot"], required=True)
    parser.add_argument("--output", default=None, help="Optional path to write the mapped config JSON")
    args = parser.parse_args()

    mapper = EngineConfigMapper(SDKConfig(args.config))
    mapped = mapper.export(args.engine)
    rendered = json.dumps(mapped, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(rendered)
        print(f"[EngineBridge] Wrote {args.engine} config to '{args.output}'")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
