from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable
import time

from .app import FeishuCodexApp
from .feishu_adapter import FeishuEventAdapter, FeishuMessageEvent
from .feishu_api import (
    FeishuEventSource,
    FeishuMessageSender,
    build_challenge_response,
    build_text_reply_payload,
    extract_challenge,
    is_empty_payload,
)


class DispatchOutcome(str, Enum):
    EMPTY = "empty"
    CHALLENGE = "challenge"
    IGNORED = "ignored"
    REPLIED = "replied"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    outcome: DispatchOutcome
    response_payload: dict[str, Any] | None = None
    reply_text: str | None = None
    receive_id: str | None = None


@runtime_checkable
class FeishuLongConnectionClient(Protocol):
    def poll(self, timeout_seconds: float | None = None) -> Mapping[str, Any] | None: ...

    def send(self, payload: Mapping[str, Any]) -> Any: ...


class FeishuLongConnectionService:
    def __init__(
        self,
        client: FeishuLongConnectionClient,
        app: FeishuCodexApp,
        *,
        adapter: FeishuEventAdapter | None = None,
        reply_receive_id_type: str = "chat_id",
    ) -> None:
        self.client = client
        self.app = app
        self.adapter = adapter or FeishuEventAdapter()
        self.reply_receive_id_type = reply_receive_id_type

    def poll_once(self, timeout_seconds: float | None = None) -> DispatchResult:
        payload = self.client.poll(timeout_seconds)
        return self.handle_payload(payload)

    def handle_payload(self, payload: Mapping[str, Any] | None) -> DispatchResult:
        if is_empty_payload(payload):
            return DispatchResult(outcome=DispatchOutcome.EMPTY)

        challenge = extract_challenge(payload)
        if challenge is not None:
            response_payload = build_challenge_response(challenge)
            return DispatchResult(
                outcome=DispatchOutcome.CHALLENGE,
                response_payload=response_payload,
            )

        if not isinstance(payload, Mapping):
            return DispatchResult(outcome=DispatchOutcome.EMPTY)

        message = self.adapter.extract_message(payload)
        if message is None:
            return DispatchResult(outcome=DispatchOutcome.IGNORED)

        reply_text = self.app.handle_message(message)
        if not reply_text:
            return DispatchResult(outcome=DispatchOutcome.IGNORED)

        receive_id = self._select_receive_id(message)
        if receive_id is None:
            return DispatchResult(outcome=DispatchOutcome.IGNORED, reply_text=reply_text)

        response_payload = build_text_reply_payload(
            receive_id,
            reply_text,
            receive_id_type=self.reply_receive_id_type,
        )
        self.client.send(response_payload)
        return DispatchResult(
            outcome=DispatchOutcome.REPLIED,
            response_payload=response_payload,
            reply_text=reply_text,
            receive_id=receive_id,
        )

    def serve(
        self,
        *,
        timeout_seconds: float | None = 1.0,
        idle_sleep_seconds: float = 0.5,
        stop_after: int | None = None,
        stop_flag: Any | None = None,
    ) -> list[DispatchResult]:
        results: list[DispatchResult] = []
        processed = 0
        while True:
            if stop_flag is not None and getattr(stop_flag, "is_set", lambda: False)():
                break
            result = self.poll_once(timeout_seconds=timeout_seconds)
            results.append(result)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
            if result.outcome in {DispatchOutcome.EMPTY, DispatchOutcome.IGNORED}:
                time.sleep(max(0.0, idle_sleep_seconds))
        return results

    def _select_receive_id(self, message: FeishuMessageEvent) -> str | None:
        if self.reply_receive_id_type == "chat_id":
            return message.chat_id or message.sender_id
        if self.reply_receive_id_type == "sender_id":
            return message.sender_id or message.chat_id
        return message.chat_id or message.sender_id

