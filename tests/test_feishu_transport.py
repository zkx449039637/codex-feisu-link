from __future__ import annotations

import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.feishu_api import build_challenge_response, build_text_reply_payload  # noqa: E402
from codex_feishu_link.feishu_adapter import FeishuMessageEvent  # noqa: E402
from codex_feishu_link.feishu_long_connection import (  # noqa: E402
    DispatchOutcome,
    FeishuLongConnectionService,
)


@dataclass
class FakeApp:
    replies: list[str]

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = replies or []
        self.messages: list[FeishuMessageEvent] = []

    def handle_message(self, message: FeishuMessageEvent) -> str:
        self.messages.append(message)
        if self.replies:
            return self.replies.pop(0)
        return "ok"


class FakeClient:
    def __init__(self, payloads: list[dict[str, object] | None]) -> None:
        self.payloads = payloads
        self.sent: list[dict[str, object]] = []

    def poll(self, timeout_seconds: float | None = None):
        if self.payloads:
            return self.payloads.pop(0)
        return None

    def send(self, payload):
        self.sent.append(dict(payload))
        return {"ok": True}


class FeishuTransportTests(unittest.TestCase):
    def test_build_text_reply_payload(self) -> None:
        payload = build_text_reply_payload("chat-1", "hello")

        self.assertEqual(payload["receive_id"], "chat-1")
        self.assertEqual(payload["receive_id_type"], "chat_id")
        self.assertEqual(payload["msg_type"], "text")
        self.assertEqual(json.loads(payload["content"]), {"text": "hello"})

    def test_build_challenge_response(self) -> None:
        self.assertEqual(build_challenge_response("abc"), {"challenge": "abc"})

    def test_handle_empty_payload(self) -> None:
        client = FakeClient([None])
        service = FeishuLongConnectionService(client=client, app=FakeApp())

        result = service.poll_once()

        self.assertEqual(result.outcome, DispatchOutcome.EMPTY)
        self.assertEqual(client.sent, [])

    def test_handle_challenge_payload(self) -> None:
        client = FakeClient([{"challenge": "xyz"}])
        service = FeishuLongConnectionService(client=client, app=FakeApp())

        result = service.poll_once()

        self.assertEqual(result.outcome, DispatchOutcome.CHALLENGE)
        self.assertEqual(result.response_payload, {"challenge": "xyz"})
        self.assertEqual(client.sent, [])

    def test_handle_message_payload_sends_reply(self) -> None:
        client = FakeClient(
            [
                {
                    "event": {
                        "sender": {"sender_id": "user-1"},
                        "message": {
                            "chat_id": "chat-1",
                            "message_id": "msg-1",
                            "content": json.dumps({"text": "status T1024"}),
                        },
                    }
                }
            ]
        )
        app = FakeApp(["task T1024 is running"])
        service = FeishuLongConnectionService(client=client, app=app)

        result = service.poll_once()

        self.assertEqual(result.outcome, DispatchOutcome.REPLIED)
        self.assertEqual(len(app.messages), 1)
        self.assertEqual(client.sent[0]["receive_id"], "chat-1")
        self.assertEqual(json.loads(client.sent[0]["content"]), {"text": "task T1024 is running"})

    def test_handle_message_without_chat_id_falls_back_to_sender(self) -> None:
        client = FakeClient(
            [
                {
                    "event": {
                        "sender": {"sender_id": "user-2"},
                        "message": {
                            "message_id": "msg-2",
                            "content": json.dumps({"text": "projects"}),
                        },
                    }
                }
            ]
        )
        app = FakeApp(["Projects:"])
        service = FeishuLongConnectionService(client=client, app=app)

        result = service.poll_once()

        self.assertEqual(result.outcome, DispatchOutcome.REPLIED)
        self.assertEqual(client.sent[0]["receive_id"], "user-2")


if __name__ == "__main__":
    unittest.main()
