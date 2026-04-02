from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.config import load_controller_config
from codex_feishu_link.feishu_api import build_feishu_http_client
from codex_feishu_link.feishu_http_client import FeishuHttpClient


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class ScriptedOpener:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[object, float | None]] = []

    def __call__(self, request, timeout: float | None = None):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("No scripted response available")
        response = self.responses.pop(0)
        return FakeResponse(response)


class FeishuHttpClientTests(unittest.TestCase):
    def test_load_controller_config_reads_feishu_settings(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".test_tmp" / f"feishu_{os.getpid()}_{uuid4().hex}"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        config_path = workspace_tmp / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "feishu": {
                        "app_id": "file-app",
                        "app_secret": "file-secret",
                        "base_url": "https://open.feishu.cn/",
                        "receive_id_type": "chat_id",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        env_backup = {
            name: os.environ.get(name)
            for name in (
                "CODEX_FEISHU_LINK_FEISHU_APP_ID",
                "CODEX_FEISHU_LINK_FEISHU_APP_SECRET",
                "CODEX_FEISHU_LINK_FEISHU_BASE_URL",
                "CODEX_FEISHU_LINK_FEISHU_RECEIVE_ID_TYPE",
            )
        }
        try:
            os.environ["CODEX_FEISHU_LINK_FEISHU_APP_ID"] = "env-app"
            os.environ["CODEX_FEISHU_LINK_FEISHU_APP_SECRET"] = "env-secret"
            os.environ["CODEX_FEISHU_LINK_FEISHU_BASE_URL"] = "https://example.feishu.cn/"
            os.environ["CODEX_FEISHU_LINK_FEISHU_RECEIVE_ID_TYPE"] = "open_id"

            config = load_controller_config(config_path)

            self.assertEqual(config.feishu_app_id, "env-app")
            self.assertEqual(config.feishu_app_secret, "env-secret")
            self.assertEqual(config.feishu_base_url, "https://example.feishu.cn")
            self.assertEqual(config.feishu_receive_id_type, "open_id")
        finally:
            for name, value in env_backup.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            shutil.rmtree(workspace_tmp, ignore_errors=True)

    def test_token_is_cached_until_expiry(self) -> None:
        opener = ScriptedOpener(
            [
                {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "token-1",
                    "expire": 3600,
                }
            ]
        )
        now = [100.0]
        client = FeishuHttpClient(
            "app-id",
            "app-secret",
            request_opener=opener,
            clock=lambda: now[0],
            token_refresh_margin_seconds=0.0,
        )

        first = client.get_tenant_access_token()
        second = client.get_tenant_access_token()

        self.assertEqual(first, "token-1")
        self.assertEqual(second, "token-1")
        self.assertEqual(len(opener.requests), 1)

    def test_send_text_message_uses_cached_token_and_receive_id_type(self) -> None:
        opener = ScriptedOpener(
            [
                {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "token-1",
                    "expire": 3600,
                },
                {
                    "code": 0,
                    "msg": "ok",
                    "data": {"message_id": "mid-1"},
                },
            ]
        )
        client = FeishuHttpClient(
            "app-id",
            "app-secret",
            base_url="https://open.feishu.cn/",
            receive_id_type="chat_id",
            request_opener=opener,
            clock=lambda: 100.0,
            token_refresh_margin_seconds=0.0,
        )

        response = client.send_text_message("chat-1", "hello", receive_id_type="chat_id")

        self.assertEqual(response["data"]["message_id"], "mid-1")
        self.assertEqual(len(opener.requests), 2)

        token_request, _ = opener.requests[0]
        message_request, message_timeout = opener.requests[1]
        self.assertIn("/open-apis/auth/v3/tenant_access_token/internal", token_request.full_url)
        self.assertIn("/open-apis/im/v1/messages?receive_id_type=chat_id", message_request.full_url)
        self.assertEqual(message_timeout, 10.0)
        self.assertEqual(message_request.get_header("Authorization"), "Bearer token-1")

        message_body = json.loads(message_request.data.decode("utf-8"))
        self.assertEqual(message_body["receive_id"], "chat-1")
        self.assertEqual(message_body["msg_type"], "text")
        self.assertEqual(json.loads(message_body["content"])["text"], "hello")

    def test_factory_uses_config_when_credentials_are_present(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".test_tmp" / f"feishu_{os.getpid()}_{uuid4().hex}"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        try:
            config_path = workspace_tmp / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "feishu_app_id": "app-id",
                        "feishu_app_secret": "app-secret",
                        "feishu_base_url": "https://example.feishu.cn/",
                        "feishu_receive_id_type": "user_id",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_controller_config(config_path)
            client = build_feishu_http_client(config, request_opener=ScriptedOpener([]), clock=lambda: 1.0)

            self.assertIsInstance(client, FeishuHttpClient)
            self.assertEqual(client.base_url, "https://example.feishu.cn")
            self.assertEqual(client.receive_id_type, "user_id")
        finally:
            shutil.rmtree(workspace_tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
