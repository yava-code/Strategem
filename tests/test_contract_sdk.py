from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from src.schema.state_map_schema import StateMap
from src.sdk.ci import write_github_actions_workflow
from src.sdk.doctor import run_doctor
from src.sdk.env import SDKGymEnv
from src.sdk.export import export_contract, plan_trace_actions
from src.sdk.generator import generate_sdk_env
from src.sdk.loader import load_adapter
from src.sdk.pipeline import run_basic_qa
from src.sdk.report import build_report
from src.sdk.scaffold import write_starter_project
from src.sdk.scout import write_suggestions
from src.sdk.validation import validate_adapter


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
            self.assertEqual(report["summary"]["first_issue"], "out_of_bounds")
            first_hit = report["oracle_hits"][0]
            self.assertIn("previous_state", first_hit)
            self.assertIn("repro_steps", first_hit)
            self.assertGreaterEqual(len(first_hit["repro_steps"]), 1)
            self.assertEqual(first_hit["repro_steps"][-1]["action"], first_hit["action"])

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

    def test_init_scaffold_exports_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            starter = Path(tmp) / "starter"
            paths = write_starter_project(starter, game_name="Starter Quest")

            self.assertTrue(paths["adapter"].exists())
            self.assertTrue(paths["guide"].exists())

            out = Path(tmp) / "contract"
            export_contract(paths["adapter"], out, game_name="Starter Quest", trace_actions=8)
            report_paths = build_report(out)
            report = json.loads(report_paths["report_json"].read_text(encoding="utf-8"))

            self.assertEqual(report["summary"]["game_name"], "Starter Quest")
            self.assertGreaterEqual(report["summary"]["state_fields"], 4)
            self.assertGreaterEqual(report["summary"]["actions"], 3)
            self.assertGreaterEqual(report["summary"]["oracles"], 2)

            with self.assertRaises(FileExistsError):
                write_starter_project(starter, game_name="Starter Quest")

    def test_validate_adapter_reports_ready_and_needs_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            starter = root / "starter"
            paths = write_starter_project(starter, game_name="Starter Quest")

            report = validate_adapter(paths["adapter"], steps=4, out_dir=root / "validation")
            self.assertEqual(report.status, "ready")
            self.assertFalse(report.errors)
            self.assertTrue((root / "validation" / "validation_report.json").exists())
            self.assertGreaterEqual(len(report.action_steps), 1)

            broken = root / "broken_adapter.py"
            broken.write_text(
                "\n".join(
                    [
                        "from bridge_maker import bm",
                        "",
                        "@bm.hp(bounds=(0, 10))",
                        "def hp():",
                        "    return 10.0",
                    ]
                ),
                encoding="utf-8",
            )
            broken_report = validate_adapter(broken, steps=2)
            self.assertEqual(broken_report.status, "needs_work")
            self.assertIn("no_actions", {f.code for f in broken_report.errors})
            self.assertIn("no_oracles", {f.code for f in broken_report.errors})

    def test_run_pipeline_creates_artifacts_and_gates_invalid_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            starter = root / "starter"
            paths = write_starter_project(starter, game_name="Run Quest")

            result = run_basic_qa(
                paths["adapter"],
                root / "run",
                game_name="Run Quest",
                validate_steps=4,
                trace_actions=8,
                trace_strategy="random",
                trace_seed=123,
            )
            self.assertEqual(result.status, "complete")
            self.assertTrue((root / "run" / "validation_report.md").exists())
            self.assertTrue((root / "run" / "state_map.json").exists())
            self.assertTrue((root / "run" / "sdk_env_generated.py").exists())
            self.assertTrue((root / "run" / "report.html").exists())
            self.assertTrue((root / "run" / "run_summary.json").exists())
            report = json.loads((root / "run" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["validation_status"], "ready")
            self.assertEqual(report["summary"]["trace_strategy"], "random")
            self.assertEqual(report["summary"]["trace_seed"], 123)
            self.assertIsNotNone(report["validation"])
            run_summary = json.loads((root / "run" / "run_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(run_summary["status"], "complete")
            self.assertFalse(run_summary["bug_found"])
            self.assertIn("report_html", run_summary["artifacts"])

            broken = root / "broken_adapter.py"
            broken.write_text(
                "\n".join(
                    [
                        "from bridge_maker import bm",
                        "",
                        "@bm.hp(bounds=(0, 10))",
                        "def hp():",
                        "    return 10.0",
                    ]
                ),
                encoding="utf-8",
            )
            failed = run_basic_qa(broken, root / "failed")
            self.assertEqual(failed.status, "validation_failed")
            self.assertTrue((root / "failed" / "validation_report.md").exists())
            self.assertTrue((root / "failed" / "run_summary.json").exists())
            self.assertFalse((root / "failed" / "state_map.json").exists())

            buggy = run_basic_qa(
                ROOT / "examples" / "buggy_roguelike.py",
                root / "buggy",
                game_name="Buggy",
                trace_actions=12,
            )
            self.assertTrue(buggy.bug_found)
            buggy_summary = json.loads((root / "buggy" / "run_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(buggy_summary["bug_found"])
            self.assertEqual(buggy_summary["report_summary"]["status"], "bug_found")

    def test_trace_action_planning_is_reproducible(self):
        actions = ["left", "right", "jump"]
        self.assertEqual(
            plan_trace_actions(actions, 5, strategy="cycle"),
            ["left", "right", "jump", "left", "right"],
        )
        self.assertEqual(
            plan_trace_actions(actions, 7, strategy="random", seed=42),
            plan_trace_actions(actions, 7, strategy="random", seed=42),
        )
        self.assertNotEqual(
            plan_trace_actions(actions, 7, strategy="random", seed=42),
            plan_trace_actions(actions, 7, strategy="random", seed=43),
        )

    def test_doctor_writes_core_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "doctor"
            report = run_doctor(out)
            self.assertIn(report.status, {"ok", "needs_work"})
            self.assertGreaterEqual(len(report.checks), 3)
            self.assertIn("training", report.optional)
            self.assertTrue((out / "doctor_report.json").exists())
            self.assertTrue((out / "doctor_report.md").exists())

    def test_github_actions_workflow_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "bridge-maker.yml"
            path = write_github_actions_workflow(
                workflow,
                adapter=r"adapters\game_bridge.py",
                run_dir=r"runs\nightly",
                trace_actions=50,
                seed=7,
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("bridge-maker doctor --out runs/nightly/doctor", text)
            self.assertIn("--adapter adapters/game_bridge.py", text)
            self.assertIn("--trace-actions 50", text)
            self.assertIn("--seed 7 --fail-on-bug", text)
            self.assertIn("actions/upload-artifact@v4", text)

            with self.assertRaises(FileExistsError):
                write_github_actions_workflow(workflow, adapter="adapters/game_bridge.py")


if __name__ == "__main__":
    unittest.main()
