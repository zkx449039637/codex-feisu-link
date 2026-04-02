from __future__ import annotations

import json
from pathlib import Path
import unittest


class ReadmeExampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_config_example_has_required_shape(self) -> None:
        config_path = self.repo_root / "config.example.json"
        payload = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIn("state_file", payload)
        self.assertIn("runtime_root", payload)
        self.assertIn("codex_executable", payload)
        self.assertIn("feishu", payload)
        self.assertIn("projects", payload)

        feishu = payload["feishu"]
        self.assertIn("app_id", feishu)
        self.assertIn("app_secret", feishu)
        self.assertIn("allowed_user_ids", feishu)
        self.assertEqual(feishu["receive_id_type"], "chat_id")
        self.assertIsInstance(feishu["allowed_user_ids"], list)

        projects = payload["projects"]
        self.assertIn("codex-feishu-link", projects)
        project = projects["codex-feishu-link"]
        self.assertTrue(Path(project["workdir"]).exists())
        self.assertEqual(project["max_parallel_tasks"], 1)

    def test_readme_mentions_windows_launcher_and_modes(self) -> None:
        readme = (self.repo_root / "README.md").read_text(encoding="utf-8")

        expected_fragments = [
            "run-service.ps1",
            "config.example.json",
            "config.local.json",
            "python -m codex_feishu_link",
            "-Mode local",
            "-Mode service",
            "CODEX_FEISHU_LINK_CONFIG",
            "feishu.app_id",
            "feishu.app_secret",
            "DEPLOYMENT.md",
        ]
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, readme)

    def test_deployment_guide_covers_multi_machine_rollout(self) -> None:
        deployment = (self.repo_root / "DEPLOYMENT.md").read_text(encoding="utf-8")

        expected_fragments = [
            "What Is Reusable",
            "What Is Machine-Specific",
            "Reuse The Same Feishu Bot Or Create A New One",
            "Second Machine Quick Start",
            "Minimal Values To Fill",
            "One bot per machine",
            "Stop the old machine's service before starting the new one",
        ]
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, deployment)

    def test_launcher_mentions_service_command(self) -> None:
        launcher = (self.repo_root / "run-service.ps1").read_text(encoding="utf-8")

        self.assertIn("python -m codex_feishu_link", launcher)
        self.assertIn("--mode", launcher)
        self.assertIn("CODEX_FEISHU_LINK_CONFIG", launcher)


if __name__ == "__main__":
    unittest.main()
