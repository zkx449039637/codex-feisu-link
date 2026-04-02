from __future__ import annotations

import json
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.app import FeishuCodexApp  # noqa: E402
from codex_feishu_link.feishu_long_connection_sdk import (  # noqa: E402
    FeishuSdkConfig,
    build_official_sdk_client,
    build_sdk_service_runtime,
    load_official_sdk_module,
)


@dataclass
class ProjectView:
    name: str
    workdir: str


class FakeBackend:
    def list_projects(self):
        return [ProjectView(name="alpha", workdir=r"D:\\alpha")]


class FakeClient:
    def __init__(
        self,
        payloads: list[dict[str, object] | None],
        *,
        app_id: str = "",
        app_secret: str = "",
        event_handler=None,
        domain: str = "",
        auto_reconnect: bool = True,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.event_handler = event_handler
        self.domain = domain
        self.auto_reconnect = auto_reconnect
        self.payloads = payloads
        self.started = False
        self.sent: list[tuple[str, str, str]] = []

    def start(self) -> None:
        self.started = True
        if self.payloads:
            for payload in list(self.payloads):
                if self.event_handler is not None:
                    self.event_handler.do_without_validation(json.dumps(payload).encode("utf-8"))

    def send_text_message(self, receive_id: str, text: str, *, receive_id_type: str = "chat_id"):
        self.sent.append((receive_id, text, receive_id_type))
        return {"ok": True}


class FakeWsClient(FakeClient):
    def __init__(self, app_id, app_secret, event_handler=None, domain=None, auto_reconnect=True):
        super().__init__(
            [],
            app_id=app_id,
            app_secret=app_secret,
            event_handler=event_handler,
            domain=domain,
            auto_reconnect=auto_reconnect,
        )


def make_fake_sdk_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(__name__="fake_sdk", ws=types.SimpleNamespace(Client=FakeWsClient))


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_text_message(self, receive_id: str, text: str, *, receive_id_type: str = "chat_id"):
        self.sent.append((receive_id, text, receive_id_type))
        return {"ok": True}


class FeishuSdkRuntimeTests(unittest.TestCase):
    def test_missing_sdk_module_returns_none(self) -> None:
        self.assertIsNone(load_official_sdk_module("definitely_missing_sdk_module"))

    def test_build_official_sdk_client_uses_ws_client_constructor(self) -> None:
        module = make_fake_sdk_module()
        config = FeishuSdkConfig(
            app_id="app-id",
            app_secret="app-secret",
            base_url="https://example.invalid",
        )

        built_client = build_official_sdk_client(config, sdk_module=module)

        self.assertIsInstance(built_client, FakeWsClient)
        self.assertEqual(built_client.app_id, "app-id")
        self.assertEqual(built_client.app_secret, "app-secret")
        self.assertEqual(built_client.domain, "https://example.invalid")

    def test_build_sdk_service_runtime_gracefully_returns_none_without_sdk(self) -> None:
        app = FeishuCodexApp(scheduler=FakeBackend())
        config = FeishuSdkConfig(
            app_id="app-id",
            app_secret="app-secret",
            sdk_module_name="definitely_missing_sdk_module",
        )

        runtime = build_sdk_service_runtime(app, sdk_config=config, sdk_module=None)

        self.assertIsNone(runtime)

    def test_sdk_runtime_sends_reply_for_received_message(self) -> None:
        app = FeishuCodexApp(scheduler=FakeBackend())
        fake_client = FakeClient(
            [
                {
                    "event": {
                        "sender": {"sender_id": "user-1"},
                        "message": {
                            "chat_id": "chat-1",
                            "message_id": "msg-1",
                            "content": json.dumps({"text": "projects"}),
                        },
                    }
                }
            ]
        )
        fake_sender = FakeSender()
        config = FeishuSdkConfig(app_id="app-id", app_secret="app-secret")

        runtime = build_sdk_service_runtime(
            app,
            sdk_config=config,
            sdk_client=fake_client,
            message_sender=fake_sender,
            stop_after=1,
        )

        self.assertIsNotNone(runtime)
        exit_code = runtime.run(app.handle_payload)

        self.assertEqual(exit_code, 0)
        self.assertTrue(fake_client.started)
        self.assertEqual(len(fake_sender.sent), 1)
        self.assertEqual(fake_sender.sent[0][0], "chat-1")
        self.assertIn("Projects:", fake_sender.sent[0][1])

    def test_sdk_runtime_uses_config_file_credentials_without_env_vars(self) -> None:
        app = FeishuCodexApp(scheduler=FakeBackend())
        fake_client = FakeClient(
            [
                {
                    "event": {
                        "sender": {"sender_id": "user-1"},
                        "message": {
                            "chat_id": "chat-1",
                            "message_id": "msg-1",
                            "content": json.dumps({"text": "projects"}),
                        },
                    }
                }
            ]
        )
        fake_sender = FakeSender()
        config = FeishuSdkConfig(
            app_id="app-id",
            app_secret="app-secret",
            base_url="https://example.invalid",
        )

        runtime = build_sdk_service_runtime(
            app,
            sdk_config=config,
            sdk_client=fake_client,
            message_sender=fake_sender,
            stop_after=1,
        )

        self.assertIsNotNone(runtime)
        runtime.run(app.handle_payload)
        self.assertEqual(fake_sender.sent[0][2], "chat_id")


if __name__ == "__main__":
    unittest.main()
