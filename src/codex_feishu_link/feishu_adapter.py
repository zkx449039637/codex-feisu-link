"""Feishu event adapter abstractions.

This module intentionally avoids any live network calls. It only normalizes
incoming webhook/event payloads and produces outgoing reply payloads that the
real Feishu transport can later send.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class FeishuMessageEvent:
    sender_id: str | None
    chat_id: str | None
    message_id: str | None
    text: str
    raw: Mapping[str, Any]


class FeishuEventAdapter:
    """Translate Feishu-style event payloads into local message objects."""

    def extract_message(self, payload: Mapping[str, Any]) -> FeishuMessageEvent | None:
        event = payload.get("event") if isinstance(payload, Mapping) else None
        if not isinstance(event, Mapping):
            return None

        message = event.get("message")
        if not isinstance(message, Mapping):
            return None

        text = self._extract_text(message)
        if not text:
            return None

        sender = event.get("sender", {})
        if not isinstance(sender, Mapping):
            sender = {}

        return FeishuMessageEvent(
            sender_id=self._pick_string(sender, "sender_id", "open_id", "union_id", "user_id"),
            chat_id=self._pick_string(message, "chat_id", "receive_id"),
            message_id=self._pick_string(message, "message_id", "msg_id"),
            text=text.strip(),
            raw=payload,
        )

    def build_text_reply(self, receive_id: str, text: str) -> dict[str, Any]:
        return {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }

    def _extract_text(self, message: Mapping[str, Any]) -> str:
        if isinstance(message.get("text"), str):
            return message["text"]

        content = message.get("content")
        if isinstance(content, str):
            try:
                decoded = json.loads(content)
            except json.JSONDecodeError:
                return content
            if isinstance(decoded, Mapping) and isinstance(decoded.get("text"), str):
                return decoded["text"]
            return content

        if isinstance(content, Mapping):
            text = content.get("text")
            if isinstance(text, str):
                return text

        return ""

    @staticmethod
    def _pick_string(source: Mapping[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
