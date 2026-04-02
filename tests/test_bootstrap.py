from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path
import sys
from importlib import import_module
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

bootstrap_module = import_module("codex_feishu_link.bootstrap")
from codex_feishu_link.bootstrap import bootstrap, build_bootstrap  # noqa: E402
from codex_feishu_link.feishu_long_connection_sdk import FeishuSdkConfig  # noqa: E402


class FakeExecutor:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.scheduler = None

    def start(self, scheduler) -> None:
        self.started = True
        self.scheduler = scheduler

    def stop(self) -> None:
        self.stopped = True


class FakeTransport:
    def __init__(self) -> None:
        self.received = []
        self.exit_code = 0

    def run(self, handler):
        reply = handler(
            {
                "event": {
                    "sender": {"sender_id": "user-1"},
                    "message": {"chat_id": "chat-1", "message_id": "msg-1", "text": "projects"},
                }
            }
        )
        self.received.append(reply)
        return self.exit_code


class BootstrapTests(unittest.TestCase):
    def test_machine_template_has_separate_machine_bot_and_projects_sections(self) -> None:
        template_path = Path(__file__).resolve().parents[1] / "machine.template.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))

        self.assertIn("machine", template)
        self.assertIn("bot", template)
        self.assertIn("projects", template)
        self.assertIn("name", template["machine"])
        self.assertIn("app_id", template["bot"])
        self.assertIsInstance(template["projects"], dict)

    def test_run_service_prefers_local_config_over_example(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "run-service.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("config.local.json", content)
        self.assertLess(content.index("config.local.json"), content.index("config.example.json"))

    def _write_config(self, tmpdir: Path) -> Path:
        config_path = tmpdir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "state_file": str(tmpdir / "state.json"),
                    "projects": {
                        "alpha": {
                            "name": "alpha",
                            "workdir": r"D:\\alpha",
                            "branch_prefix": "codex/",
                            "max_parallel_tasks": 1,
                        }
                    },
                    "feishu": {
                        "app_id": "cfg-app-id",
                        "app_secret": "cfg-app-secret",
                        "base_url": "https://open.feishu.cn",
                        "receive_id_type": "chat_id",
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _workspace(self) -> Path:
        root = Path(__file__).resolve().parents[1] / ".test_tmp"
        workspace = root / f"bootstrap_{os.getpid()}_{uuid4().hex}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def test_build_bootstrap_uses_config_and_scheduler(self) -> None:
        workspace = self._workspace()
        try:
            bundle = build_bootstrap(self._write_config(workspace))

            self.assertIn("alpha", bundle.config.projects)
            self.assertEqual(bundle.scheduler.list_projects()[0].name, "alpha")
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_local_repl_mode_runs_without_transport(self) -> None:
        workspace = self._workspace()
        try:
            bundle = build_bootstrap(self._write_config(workspace))

            outputs: list[str] = []
            inputs = iter(["projects"])

            def fake_input(_: str) -> str:
                try:
                    return next(inputs)
                except StopIteration as exc:
                    raise EOFError from exc

            exit_code = bundle.run_local_repl(input_fn=fake_input, output_fn=outputs.append)

            self.assertEqual(exit_code, 0)
            self.assertTrue(outputs[0].startswith("Supported commands:"))
            self.assertTrue(any(line.startswith("Projects:") for line in outputs))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_service_mode_wires_executor_and_transport(self) -> None:
        workspace = self._workspace()
        try:
            bundle = build_bootstrap(self._write_config(workspace))
            executor = FakeExecutor()
            transport = FakeTransport()
            bundle.executor = executor
            bundle.transport = transport

            exit_code = bundle.run_service()

            self.assertEqual(exit_code, 0)
            self.assertTrue(executor.started)
            self.assertTrue(executor.stopped)
            self.assertEqual(transport.received[0], "Projects:\n- name=alpha, workdir=D:\\\\alpha, branch_prefix=codex/, max_parallel_tasks=1")
            self.assertIsNotNone(executor.scheduler)
            self.assertEqual(executor.scheduler.list_tasks(), [])
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_default_transport_uses_config_file_credentials_without_env_vars(self) -> None:
        workspace = self._workspace()
        original = bootstrap_module.build_sdk_service_runtime
        original_loader = bootstrap_module.load_feishu_sdk_config
        captured: dict[str, object] = {}

        def fake_build_sdk_service_runtime(app, *, sdk_config=None, sdk_module=None, sdk_client=None, stop_after=None):
            captured["sdk_config"] = sdk_config

            class FakeRuntime:
                def run(self, handler):
                    return 0

            return FakeRuntime()

        def fail_loader():
            raise AssertionError("load_feishu_sdk_config should not be used when controller config has credentials")

        try:
            bundle = build_bootstrap(self._write_config(workspace))
            self.assertEqual(bundle.config.feishu_app_id, "cfg-app-id")
            self.assertEqual(bundle.config.feishu_app_secret, "cfg-app-secret")
            bootstrap_module.build_sdk_service_runtime = fake_build_sdk_service_runtime
            bootstrap_module.load_feishu_sdk_config = fail_loader

            transport = bundle._build_default_transport()

            self.assertIsNotNone(transport)
            sdk_config = captured["sdk_config"]
            self.assertIsInstance(sdk_config, FeishuSdkConfig)
            self.assertEqual(sdk_config.app_id, "cfg-app-id")
            self.assertEqual(sdk_config.app_secret, "cfg-app-secret")
            self.assertEqual(sdk_config.base_url, "https://open.feishu.cn")
            self.assertEqual(sdk_config.receive_id_type, "chat_id")
        finally:
            bootstrap_module.build_sdk_service_runtime = original
            bootstrap_module.load_feishu_sdk_config = original_loader
            shutil.rmtree(workspace, ignore_errors=True)

    def test_bootstrap_wrapper_defaults_to_local_mode(self) -> None:
        workspace = self._workspace()
        try:
            config_path = self._write_config(workspace)
            outputs: list[str] = []

            def fake_input(_: str) -> str:
                raise EOFError

            exit_code = bootstrap(config_path=config_path, input_fn=fake_input, output_fn=outputs.append)

            self.assertEqual(exit_code, 0)
            self.assertTrue(outputs[0].startswith("Supported commands:"))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
