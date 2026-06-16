from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from src.schema.state_map_schema import StateMap
from src.sdk.env import SDKGymEnv
from src.sdk.export import export_contract
from src.sdk.generator import generate_sdk_env
from src.sdk.loader import load_adapter
from src.sdk.report import build_report
from src.sdk.scout import write_suggestions


ROOT = Path(__file__).resolve().parents[1]


class ContractSDKTests(unittest.TestCase):
    def test_buggy_roguelike_export_report_and_generated_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "buggy"
            export_contract(
                ROOT / "examples" / "buggy_roguelike.py",
                out,
                game_name="buggy_roguelike_test",
                trace_actions=12,
            )

            state_map = StateMap.load(out / "state_map.json")
            action_map = json.loads((out / "action_map.json").read_text(encoding="utf-8"))
            oracle_map = json.loads((out / "oracle_map.json").read_text(encoding="utf-8"))

            self.assertEqual(state_map.game_name, "buggy_roguelike_test")
            self.assertGreaterEqual(len(state_map.state_variables), 5)
            self.assertGreaterEqual(len(action_map["actions"]), 4)
            self.assertGreaterEqual(len(oracle_map["oracles"]), 1)

            reports = build_report(out)
            report = json.loads(reports["report_json"].read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["status"], "bug_found")
            self.assertGreaterEqual(report["summary"]["oracle_hits"], 1)

            env_path = generate_sdk_env(out)
            spec = importlib.util.spec_from_file_location("generated_buggy_env", env_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            env = mod.make_env(max_steps=8)
            obs, info = env.reset()
            self.assertEqual(obs.shape, env.observation_space.shape)
            self.assertIn("state", info)

            obs, reward, terminated, truncated, info = env.step(0)
            self.assertEqual(obs.shape, env.observation_space.shape)
            self.assertIsInstance(float(reward), float)
            self.assertIsInstance(terminated, bool)
            self.assertIsInstance(truncated, bool)
            self.assertIn("action", info)

    def test_sdk_env_smoke_over_annotated_dummy(self):
        load_adapter(ROOT / "examples" / "annotated_dummy.py")
        env = SDKGymEnv(max_steps=20)
        obs, info = env.reset()
        self.assertEqual(obs.shape, env.observation_space.shape)
        self.assertIn("hp", info["state"])

        for i in range(20):
            obs, reward, terminated, truncated, info = env.step(i)
            self.assertEqual(obs.shape, env.observation_space.shape)
            self.assertIsInstance(float(reward), float)
            self.assertIn("state", info)
            if terminated or truncated:
                break

    def test_codescout_writes_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "suggestions"
            json_path, md_path = write_suggestions(ROOT / "examples", base)
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertGreater(len(data), 0)


if __name__ == "__main__":
    unittest.main()
