"""
src/training/swarm_trainer.py

Phase 4 — Ray/RLlib PPO + built-in ICM (Curiosity) swarm trainer.

Cloud integrations (all optional, each gracefully falls back):
  Wandb  — set WANDB_API_KEY; otherwise telemetry is silently disabled
  Modal  — set MODAL_TOKEN_ID; otherwise falls back to local Ray.init()
  Azure  — set AZURE_STORAGE_CONNECTION_STRING; otherwise saves to ./checkpoints/

CLI:
  python -m src.training.swarm_trainer --mode local --iterations 50 --pid <PID>
  python -m src.training.swarm_trainer --mode modal --iterations 50
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ── Capability detection ──────────────────────────────────────────────────────
_WANDB_KEY = os.environ.get("WANDB_API_KEY")
_AZURE_CONN = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
_MODAL_ID   = os.environ.get("MODAL_TOKEN_ID")

try:
    import ray
    from ray.rllib.algorithms.ppo import PPOConfig
    from ray.rllib.algorithms.callbacks import DefaultCallbacks
    from ray.tune.registry import register_env
    _RAY_OK = True
except ImportError:
    _RAY_OK = False
    DefaultCallbacks = object  # sentinel so SwarmMetricsCallback can be defined regardless

try:
    import wandb as _wandb_mod
    _WANDB_OK = bool(_WANDB_KEY)
except ImportError:
    _wandb_mod = None  # type: ignore[assignment]
    _WANDB_OK  = False

try:
    import modal as _modal_mod
    _MODAL_OK = bool(_MODAL_ID)
except ImportError:
    _modal_mod = None  # type: ignore[assignment]
    _MODAL_OK  = False

try:
    from azure.storage.blob import BlobServiceClient
    _AZURE_OK = bool(_AZURE_CONN)
except ImportError:
    BlobServiceClient = None  # type: ignore[assignment]
    _AZURE_OK = False

try:
    from src.agents.oracle_client import OracleClient
    _ORACLE_AVAIL = True
except ImportError:
    _ORACLE_AVAIL = False

try:
    from src.dashboard import DashboardServer
    _DASH_AVAIL = True
except ImportError:
    _DASH_AVAIL = False

# ── Constants ─────────────────────────────────────────────────────────────────
ENV_ID          = "live_env_v1"
CHECKPOINT_DIR  = Path("./checkpoints")
DEFAULT_PROJECT = "bridge-maker"
_ICM_DEFAULTS: dict = {"eta": 1.0, "lr": 1e-3, "feature_dim": 64, "beta": 0.2}

# ── Phase 5 module-level singletons (safe: num_workers=0 keeps everything in driver) ──
_ORACLE:       Optional["OracleClient"]    = None
_DASHBOARD:    Optional["DashboardServer"] = None
_FREEZE_TOTAL: int = 0


# ── Simulated env for Modal (no pymem / pydirectinput) ───────────────────────
def _make_sim_env(_env_config: dict):
    """
    Mirrors LiveEnv's obs/action space (Box(2,) + Discrete(4)) without
    any Windows-only dependencies. Used by the Modal execution path where
    the host OS is a Linux container.
    """
    import gymnasium as gym
    import numpy as np

    class _SimEnv(gym.Env):
        metadata = {"render_modes": []}

        def __init__(self):
            self.observation_space = gym.spaces.Box(
                low=0.0, high=1.0, shape=(2,), dtype=np.float32
            )
            self.action_space = gym.spaces.Discrete(4)
            self._health = 1.0
            self._pos_x  = 0.05
            self._steps  = 0

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            self._health, self._pos_x, self._steps = 1.0, 0.05, 0
            return np.array([self._health, self._pos_x], dtype=np.float32), {}

        def step(self, action):
            self._steps += 1
            delta        = (int(action) - 1.5) * 0.04
            self._pos_x  = float(
                np.clip(self._pos_x + delta + np.random.normal(0, 0.01), 0.0, 1.0)
            )
            self._health = max(0.0, self._health - 0.005)
            obs        = np.array([self._health, self._pos_x], dtype=np.float32)
            reward     = self._pos_x * 0.5
            terminated = self._health <= 0.0 or self._steps >= 200
            return obs, float(reward), terminated, False, {}

        def close(self) -> None:
            pass

    return _SimEnv()


# ── Live env factory (Windows + pymem) ───────────────────────────────────────
def _make_live_env(env_config: dict):
    """
    PID-aware LiveEnv factory for RLlib workers.

    RLlib calls env.reset() without arguments, but LiveEnv.reset() needs
    options={"pid": pid} to avoid attaching to the wrong python.exe when
    multiple python processes exist. _PinnedLiveEnv injects the PID
    transparently so the generated file needs no modification.
    """
    from src.generation.live_env_generated import LiveEnv

    pid        = int(env_config.get("pid", 0))
    game_exe   = str(env_config.get("game_exe", "python.exe"))
    tick_sleep = float(env_config.get("tick_sleep", 0.5))

    class _PinnedLiveEnv(LiveEnv):
        def reset(self, *, seed=None, options=None):
            import numpy as np

            opts = dict(options or {})
            if pid:
                opts["pid"] = pid

            # Fast path: addresses already resolved — just validate with a single read.
            # Avoids the full-process float scan (~60s) on every episode reset, which
            # is prohibitive during training (many short episodes).
            if self._pm is not None and any(v > 0 for v in self._addrs.values()):
                try:
                    anchor = next(v for v in self._addrs.values() if v > 0)
                    self._pm.read_float(anchor)          # raises OSError if target died
                    self._prev_obs = None
                    self._freeze_n = 0
                    return self._get_obs(), {"addrs": {k: hex(v) for k, v in self._addrs.items()}}
                except OSError:
                    self._pm    = None
                    self._addrs = {}

            # Slow path: full scan (first episode per process session).
            # Also handles re-attach when the target process has restarted.
            try:
                return super().reset(seed=seed, options=opts)
            except Exception as exc:
                # Target unavailable (process died, PID stale, access denied).
                # Return zero obs so RLlib sees a terminated episode rather than a crash.
                print(f"[PinnedLiveEnv] Target unavailable: {exc}")
                obs = np.zeros(self.observation_space.shape, dtype=np.float32)
                return obs, {"error": str(exc)}

        def step(self, action: int):
            global _FREEZE_TOTAL
            obs, reward, terminated, truncated, info = super().step(action)
            # _freeze_n > 0 means termination was caused by freeze (obs unchanged),
            # not by the game-over condition (health == 0).
            if terminated and getattr(self, "_freeze_n", 0) > 0:
                _FREEZE_TOTAL += 1
                if _ORACLE is not None:
                    action_str = _ORACLE.attempt_unfreeze()
                    if action_str:
                        self._freeze_n = 0
                        terminated = False
                        info["oracle_action"] = action_str
                        if _DASHBOARD is not None:
                            _DASHBOARD.log_oracle(action_str)
            return obs, reward, terminated, truncated, info

    return _PinnedLiveEnv(game_exe=game_exe, tick_sleep=tick_sleep)


# ── Metrics callback ──────────────────────────────────────────────────────────
class SwarmMetricsCallback(DefaultCallbacks):
    """
    LiveEnv-native RLlib callback.

    Replaces DashboardBridgeCallbacks (src/ray_callbacks.py) which depends on
    env.reward_generator, env.agent_pos, and env.logger — attributes that do
    not exist on the auto-generated LiveEnv.
    """

    def on_episode_start(self, *, episode, **kwargs) -> None:
        episode.user_data["pos_x_travel"] = 0.0
        episode.user_data["prev_obs"]     = None

    def on_episode_step(self, *, episode, **kwargs) -> None:
        try:
            obs  = episode.last_obs_for()
            prev = episode.user_data.get("prev_obs")
            if prev is not None and len(obs) > 1:
                episode.user_data["pos_x_travel"] += abs(float(obs[1]) - float(prev[1]))
            import numpy as np
            episode.user_data["prev_obs"] = obs.copy()
        except Exception:
            pass

    def on_episode_end(self, *, episode, **kwargs) -> None:
        try:
            obs = episode.last_obs_for()
            episode.custom_metrics["health_final"]   = float(obs[0])
            episode.custom_metrics["pos_x_travel"]   = float(
                episode.user_data.get("pos_x_travel", 0.0)
            )
            episode.custom_metrics["episode_length"] = int(episode.length)
        except Exception:
            pass

    def on_train_result(self, *, result, **kwargs) -> None:
        iteration = int(result.get("training_iteration", 0))
        reward    = float(
            result.get("env_runners", {}).get("episode_return_mean")
            or result.get("episode_reward_mean")
            or 0.0
        ) or 0.0

        # Always push to dashboard (does not require Wandb).
        if _DASHBOARD is not None:
            _DASHBOARD.update_training_metrics(iteration, reward, _FREEZE_TOTAL)

        if not (_WANDB_OK and _wandb_mod is not None and _wandb_mod.run):
            return
        env_runners = result.get("env_runners", result)
        curiosity_loss = float(
            result.get("info", {})
                  .get("learner", {})
                  .get("default_policy", {})
                  .get("curiosity_module", {})
                  .get("forward_loss", 0.0)
        )
        _wandb_mod.log({
            "train/reward_mean":    float(env_runners.get(
                "episode_return_mean", result.get("episode_reward_mean", 0.0)
            )),
            "train/reward_max":     float(env_runners.get("episode_return_max", 0.0)),
            "train/episode_length": float(env_runners.get("episode_len_mean", 0.0)),
            "icm/forward_loss":     curiosity_loss,
            "train/iteration":      iteration,
        })


# ── Artifact sync ─────────────────────────────────────────────────────────────
class ArtifactSync:
    """Uploads checkpoints to Azure Blob Storage; falls back to local ./checkpoints/."""

    def __init__(self, container: str = "bridge-maker-ckpts") -> None:
        if _AZURE_OK:
            self._client    = BlobServiceClient.from_connection_string(_AZURE_CONN)
            self._container = container
            try:
                self._client.create_container(container)
            except Exception:
                pass  # container already exists
            print(f"[ArtifactSync] Azure Blob Storage -> container '{container}'")
        else:
            CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
            print(f"[ArtifactSync] local storage -> {CHECKPOINT_DIR.resolve()}")

    def push(self, local_path: Path, blob_prefix: str) -> None:
        local_path = Path(local_path)
        if not local_path.exists():
            print(f"[ArtifactSync] WARN: source not found: {local_path}")
            return
        if _AZURE_OK:
            paths = list(local_path.rglob("*")) if local_path.is_dir() else [local_path]
            for fp in paths:
                if not fp.is_file():
                    continue
                rel  = fp.relative_to(local_path) if local_path.is_dir() else Path(fp.name)
                name = f"{blob_prefix}/{rel}".replace("\\", "/")
                with open(fp, "rb") as fh:
                    self._client.get_blob_client(self._container, name) \
                                 .upload_blob(fh, overwrite=True)
            print(f"[ArtifactSync] Azure <- {blob_prefix}")
        else:
            dest = CHECKPOINT_DIR / blob_prefix
            # Skip when source == destination (algo.save("checkpoints/X") returns "checkpoints/X")
            if local_path.resolve() == dest.resolve():
                print(f"[ArtifactSync] local: checkpoint already at {dest}")
                return
            if dest.exists():
                shutil.rmtree(dest)
            if local_path.is_dir():
                shutil.copytree(local_path, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, dest)
            print(f"[ArtifactSync] local <- {dest}")


# ── PPO + Curiosity config builder ────────────────────────────────────────────
def _build_swarm_ppo(
    env_id:      str,
    env_config:  dict,
    num_workers: int,
    icm_cfg:     dict,
    batch_size:  int = 2000,
) -> "PPOConfig":
    """
    Reuses the build pattern from src/train_rllib.py (lines 42-107):
      - old API stack pinned (enable_rl_module_and_learner=False)
      - dual env_runners/rollouts path for RLlib version resilience
      - Curiosity exploration in try/except (version-safe)
    No SDKConfig dependency — defaults are hardcoded directly.
    """
    config = (
        PPOConfig()
        .environment(env=env_id, env_config=env_config)
        .framework("torch")
        .training(
            lr=3e-4,
            gamma=0.99,
            train_batch_size=batch_size,
            num_epochs=10,
            entropy_coeff=0.01,
        )
        .callbacks(SwarmMetricsCallback)
    )

    try:
        config = config.env_runners(num_env_runners=num_workers)
    except Exception:
        config = config.rollouts(num_rollout_workers=num_workers)

    try:
        config = config.api_stack(
            enable_rl_module_and_learner=False,
            enable_env_runner_and_connector_v2=False,
        )
    except Exception:
        pass

    # Curiosity requires num_workers=0 — it can only run in the driver process.
    # Force a re-configuration of the worker count when ICM is enabled.
    # (RLlib source: curiosity.py line 113: "num_workers must be 0")
    try:
        config = config.env_runners(num_env_runners=0)
    except Exception:
        config = config.rollouts(num_rollout_workers=0)
    print("[SwarmTrainer] Curiosity requires num_workers=0 — rollouts run in driver")

    # Configure built-in Curiosity (ICM) exploration.
    # Ray 2.50+ deprecated .exploration(); use update_from_dict() to bypass
    # the method guard while still targeting the old API stack.
    _curiosity_cfg = {
        "explore": True,
        "exploration_config": {
            "type":               "Curiosity",
            "eta":                icm_cfg.get("eta", 1.0),
            "lr":                 icm_cfg.get("lr", 1e-3),
            "feature_dim":        icm_cfg.get("feature_dim", 64),
            "feature_net_config": {"fcnet_hiddens": [64], "fcnet_activation": "relu"},
            "inverse_net_hiddens":    [64],
            "inverse_net_activation": "relu",
            "forward_net_hiddens":    [64],
            "forward_net_activation": "relu",
            "beta":               icm_cfg.get("beta", 0.2),
            "sub_exploration":    {"type": "StochasticSampling"},
        },
    }
    try:
        config.update_from_dict(_curiosity_cfg)
        print("[SwarmTrainer] Curiosity (ICM) exploration active")
    except Exception as exc:
        print(f"[SwarmTrainer] Curiosity exploration not applied ({exc})")

    return config


def _resolve_ckpt_path(ckpt) -> str:
    """Extract a filesystem path string from whatever algo.save() returns.
    Ray 2.9–2.49 returns str; Ray 2.50+ returns _TrainingResult or Checkpoint.
    """
    if isinstance(ckpt, str):
        return ckpt
    # Ray 2.50+: Result object with .checkpoint.path (may be URI or Path)
    sub = getattr(ckpt, "checkpoint", None)
    if sub is not None:
        p = getattr(sub, "path", None)
        if p is not None:
            # Strip "file:///" URI prefix on Windows
            s = str(p)
            if s.startswith("file:///"):
                s = s[8:]
            return s
    # Fallback: try .path directly
    p = getattr(ckpt, "path", None)
    if p is not None:
        s = str(p)
        if s.startswith("file:///"):
            s = s[8:]
        return s
    return str(ckpt)


# ── Local training loop ───────────────────────────────────────────────────────
def _run_local(
    algo,
    iterations:    int,
    sync:          ArtifactSync,
    wandb_project: str,
    run_name:      str,
) -> str:
    if _WANDB_OK and _wandb_mod is not None:
        _wandb_mod.init(project=wandb_project, name=run_name, resume="allow")
        print(f"[SwarmTrainer] Wandb run: {_wandb_mod.run.url}")
    else:
        print("[SwarmTrainer] Wandb not configured — telemetry disabled")

    ckpt_path = ""
    try:
        for it in range(iterations):
            result  = algo.train()
            # Old API stack uses "episode_reward_mean"; new stack uses "episode_return_mean"
            # inside the "env_runners" sub-dict.
            reward  = float(
                result.get("episode_reward_mean")
                or result.get("env_runners", {}).get("episode_return_mean")
                or 0.0
            )
            print(f"[SwarmTrainer] iter {it + 1:>4}/{iterations}  reward={reward:+.3f}")
            if (it + 1) % 10 == 0:
                ckpt_path = _resolve_ckpt_path(algo.save(str(CHECKPOINT_DIR / f"iter_{it + 1}")))
                sync.push(Path(ckpt_path), f"iter_{it + 1}")
    except KeyboardInterrupt:
        print("[SwarmTrainer] Interrupted — saving final checkpoint ...")
    finally:
        ckpt_path = _resolve_ckpt_path(algo.save(str(CHECKPOINT_DIR / "final")))
        sync.push(Path(ckpt_path), "final")
        print(f"[SwarmTrainer] Checkpoint: {ckpt_path}")
        algo.stop()
        ray.shutdown()
        if _WANDB_OK and _wandb_mod is not None and _wandb_mod.run:
            _wandb_mod.finish()
    return ckpt_path


def _run_training_local(cfg: dict) -> None:
    global _ORACLE, _DASHBOARD

    # register_env pickles _make_live_env via cloudpickle. At that moment, module
    # globals must be picklable. DashboardServer contains threading.Lock (not picklable),
    # so we init Oracle + Dashboard AFTER register_env + build_algo — they will be set
    # before the first algo.train() call where step() actually runs.
    ray.init(ignore_reinit_error=True, include_dashboard=False)
    env_config = {k: cfg[k] for k in ("game_exe", "pid", "tick_sleep")}
    register_env(ENV_ID, _make_live_env)
    algo = _build_swarm_ppo(
        ENV_ID, env_config, cfg["num_workers"], _ICM_DEFAULTS.copy(),
        batch_size=cfg.get("batch_size", 2000),
    ).build_algo()

    dashboard_port = int(cfg.get("dashboard_port", 8000))
    if _DASH_AVAIL and not cfg.get("no_dashboard"):
        _DASHBOARD = DashboardServer(port=dashboard_port)
        _DASHBOARD.start()
        print(f"[SwarmTrainer] Dashboard: http://localhost:{dashboard_port}/")
    else:
        print("[SwarmTrainer] Dashboard disabled.")

    if _ORACLE_AVAIL and not cfg.get("no_oracle"):
        _ORACLE = OracleClient(window_title=cfg.get("game_title", "") or None)
        status  = "ACTIVE" if _ORACLE.available else "GROQ_API_KEY missing — Oracle is no-op"
        print(f"[SwarmTrainer] Oracle: {status}")
    else:
        print("[SwarmTrainer] Oracle disabled.")

    _run_local(
        algo,
        iterations=cfg["iterations"],
        sync=ArtifactSync(),
        wandb_project=cfg["wandb_project"],
        run_name="swarm-local",
    )


# ── Modal App stub ────────────────────────────────────────────────────────────
if _MODAL_OK and _modal_mod is not None:
    _modal_app    = _modal_mod.App("bridge-maker-trainer")
    _bridge_image = (
        _modal_mod.Image.debian_slim(python_version="3.11")
        .pip_install([
            "ray[rllib]>=2.9.0",
            "torch>=2.0.0",
            "gymnasium>=0.29.0",
            "numpy<2.0.0",
            "wandb>=0.15.0",
            "python-dotenv>=1.0.0",
        ])
    )

    @_modal_app.function(image=_bridge_image, timeout=7200, gpu="T4")
    def _modal_train_remote(cfg: dict) -> str:
        """
        Self-contained training function on Modal's cloud hardware.

        Uses a simulated env (same obs/action space as LiveEnv) because pymem
        and pydirectinput require Windows; Modal workers run Linux containers.
        Returns the path to the saved checkpoint (on the Modal worker's filesystem).
        """
        import os
        import shutil
        from pathlib import Path

        import numpy as np
        import gymnasium as gym
        import ray
        from ray.rllib.algorithms.ppo import PPOConfig
        from ray.tune.registry import register_env

        _CKPT_DIR = Path("/tmp/bridge_maker_checkpoints")
        _CKPT_DIR.mkdir(parents=True, exist_ok=True)
        _SIM_ID   = "bridge_maker_modal_sim"

        class _ModalSimEnv(gym.Env):
            metadata = {"render_modes": []}

            def __init__(self, env_config=None):
                self.observation_space = gym.spaces.Box(
                    low=0.0, high=1.0, shape=(2,), dtype=np.float32
                )
                self.action_space = gym.spaces.Discrete(4)
                self._health = 1.0
                self._pos_x  = 0.05
                self._steps  = 0

            def reset(self, *, seed=None, options=None):
                super().reset(seed=seed)
                self._health, self._pos_x, self._steps = 1.0, 0.05, 0
                return np.array([self._health, self._pos_x], dtype=np.float32), {}

            def step(self, action):
                self._steps += 1
                delta        = (int(action) - 1.5) * 0.04
                self._pos_x  = float(
                    np.clip(self._pos_x + delta + np.random.normal(0, 0.01), 0.0, 1.0)
                )
                self._health = max(0.0, self._health - 0.005)
                obs        = np.array([self._health, self._pos_x], dtype=np.float32)
                reward     = self._pos_x * 0.5
                terminated = self._health <= 0.0 or self._steps >= 200
                return obs, float(reward), terminated, False, {}

            def close(self) -> None:
                pass

        register_env(_SIM_ID, lambda _: _ModalSimEnv())
        ray.init(ignore_reinit_error=True, include_dashboard=False)

        config = (
            PPOConfig()
            .environment(env=_SIM_ID)
            .framework("torch")
            .training(lr=3e-4, gamma=0.99, train_batch_size=2000, num_sgd_iter=10)
        )
        try:
            config = config.env_runners(num_env_runners=cfg.get("num_workers", 1))
        except Exception:
            config = config.rollouts(num_rollout_workers=cfg.get("num_workers", 1))
        try:
            config = config.api_stack(
                enable_rl_module_and_learner=False,
                enable_env_runner_and_connector_v2=False,
            )
        except Exception:
            pass
        try:
            config = config.exploration(
                explore=True,
                exploration_config={
                    "type": "Curiosity", "eta": 1.0, "lr": 1e-3, "feature_dim": 64,
                    "feature_net_config": {"fcnet_hiddens": [64], "fcnet_activation": "relu"},
                    "inverse_net_hiddens":    [64], "inverse_net_activation": "relu",
                    "forward_net_hiddens":    [64], "forward_net_activation": "relu",
                    "beta": 0.2, "sub_exploration": {"type": "StochasticSampling"},
                },
            )
        except Exception:
            pass

        algo       = config.build()
        iterations = int(cfg.get("iterations", 50))
        ckpt_path  = ""
        try:
            for it in range(iterations):
                result = algo.train()
                reward = float(
                    result.get("env_runners", result).get(
                        "episode_return_mean", result.get("episode_reward_mean", 0.0)
                    )
                )
                print(f"[Modal] iter {it + 1:>4}/{iterations}  reward={reward:+.3f}")
        finally:
            ckpt_path = algo.save(str(_CKPT_DIR / "final"))
            algo.stop()
            ray.shutdown()
        return ckpt_path


def _run_modal(cfg: dict) -> None:
    if not (_MODAL_OK and _modal_mod is not None):
        print("[SwarmTrainer] Modal not configured (MODAL_TOKEN_ID not set) — falling back to local")
        _run_training_local(cfg)
        return
    print("[SwarmTrainer] Launching on Modal.com ...")
    with _modal_app.run():
        ckpt = _modal_train_remote.remote(cfg)
    print(f"[SwarmTrainer] Modal training complete. Remote checkpoint: {ckpt}")


# ── Public API ────────────────────────────────────────────────────────────────
def train(
    game_exe:       str  = "python.exe",
    game_pid:       int  = 0,
    iterations:     int  = 50,
    num_workers:    int  = 1,
    mode:           str  = "local",
    wandb_project:  str  = DEFAULT_PROJECT,
    map_path:       str  = "state_map_python.json",
    batch_size:     int  = 2000,
    dashboard_port: int  = 8000,
    game_title:     str  = "",
    no_oracle:      bool = False,
    no_dashboard:   bool = False,
) -> None:
    if not _RAY_OK:
        sys.exit(
            "[SwarmTrainer] ray[rllib] is not installed.\n"
            "  pip install 'ray[rllib]>=2.9.0'"
        )
    cfg = {
        "game_exe":       game_exe,
        "pid":            game_pid,
        "tick_sleep":     0.5,
        "iterations":     iterations,
        "num_workers":    num_workers,
        "wandb_project":  wandb_project,
        "game_script":    "tools/dummy_target.py",
        "batch_size":     batch_size,
        "dashboard_port": dashboard_port,
        "game_title":     game_title,
        "no_oracle":      no_oracle,
        "no_dashboard":   no_dashboard,
    }
    if mode == "modal":
        _run_modal(cfg)
    else:
        _run_training_local(cfg)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(
        description="Bridge-Maker Swarm Trainer — Phase 4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Cloud env vars:\n"
            "  WANDB_API_KEY                      — enables Wandb telemetry\n"
            "  MODAL_TOKEN_ID + MODAL_TOKEN_SECRET — enables Modal.com execution\n"
            "  AZURE_STORAGE_CONNECTION_STRING     — enables Azure checkpoint sync\n"
        ),
    )
    ap.add_argument("--mode",          choices=["local", "modal"], default="local",
                    help="Execution backend (default: local)")
    ap.add_argument("--iterations",    type=int,   default=50,
                    help="Training iterations (default: 50)")
    ap.add_argument("--workers",       type=int,   default=1,
                    help="RLlib rollout workers (default: 1)")
    ap.add_argument("--game-exe",      default="python.exe",
                    help="Game process name for pymem attach (default: python.exe)")
    ap.add_argument("--pid",           type=int,   default=0,
                    help="Game process PID — 0 means attach by name")
    ap.add_argument("--map",           default="state_map_python.json",
                    help="State map JSON (default: state_map_python.json)")
    ap.add_argument("--wandb-project", default=DEFAULT_PROJECT,
                    help=f"Wandb project name (default: {DEFAULT_PROJECT})")
    ap.add_argument("--batch-size",      type=int,   default=2000,
                    help="RLlib train_batch_size per iteration (default: 2000; use 200 for quick tests)")
    ap.add_argument("--dashboard-port",  type=int,   default=8000,
                    help="Dashboard HTTP port (default: 8000)")
    ap.add_argument("--game-title",      default="",
                    help="Window title for Oracle screenshot (empty = fullscreen capture)")
    ap.add_argument("--no-oracle",       action="store_true",
                    help="Disable VLM Oracle even if GROQ_API_KEY is set")
    ap.add_argument("--no-dashboard",    action="store_true",
                    help="Disable the dashboard HTTP server")
    args = ap.parse_args()
    train(
        game_exe=args.game_exe,
        game_pid=args.pid,
        iterations=args.iterations,
        num_workers=args.workers,
        mode=args.mode,
        wandb_project=args.wandb_project,
        map_path=args.map,
        batch_size=args.batch_size,
        dashboard_port=args.dashboard_port,
        game_title=args.game_title,
        no_oracle=args.no_oracle,
        no_dashboard=args.no_dashboard,
    )


if __name__ == "__main__":
    main()
