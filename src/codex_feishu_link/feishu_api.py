from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .config import ControllerConfig
from .feishu_http_client import FeishuHttpClient


@runtime_checkable
class FeishuMessageSender(Protocol):
    def send(self, payload: Mapping[str, Any]) -> Any: ...


@runtime_checkable
class FeishuEventSource(Protocol):
    def poll(self, timeout_seconds: float | None = None) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class FeishuTextReply:
    receive_id: str
    text: str
    receive_id_type: str = "chat_id"
    msg_type: str = "text"

    def to_payload(self) -> dict[str, Any]:
        return {
            "receive_id_type": self.receive_id_type,
            "receive_id": self.receive_id,
            "msg_type": self.msg_type,
            "content": json.dumps({"text": self.text}, ensure_ascii=False),
        }


def build_text_reply_payload(
    receive_id: str,
    text: str,
    *,
    receive_id_type: str = "chat_id",
) -> dict[str, Any]:
    return FeishuTextReply(
        receive_id=receive_id,
        text=text,
        receive_id_type=receive_id_type,
    ).to_payload()


def build_feishu_http_client(
    config: ControllerConfig,
    *,
    request_opener: Callable[..., Any] | None = None,
    clock: Callable[[], float] | None = None,
    timeout_seconds: float | None = None,
) -> FeishuHttpClient | None:
    """Construct a reusable Feishu API client from controller config.

    Returns ``None`` when the app credentials are not configured, so callers can
    opt into a dry-run or local-only mode without special-casing the config.
    """

    if not config.feishu_app_id or not config.feishu_app_secret:
        return None
    kwargs: dict[str, Any] = {
        "base_url": config.feishu_base_url,
        "receive_id_type": config.feishu_receive_id_type,
    }
    if request_opener is not None:
        kwargs["request_opener"] = request_opener
    if clock is not None:
        kwargs["clock"] = clock
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds
    return FeishuHttpClient(config.feishu_app_id, config.feishu_app_secret, **kwargs)


def build_challenge_response(challenge: str) -> dict[str, str]:
    return {"challenge": challenge}


def extract_challenge(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    challenge = payload.get("challenge")
    if isinstance(challenge, str) and challenge.strip():
        return challenge.strip()
    return None


def is_empty_payload(payload: Mapping[str, Any] | None) -> bool:
    return not isinstance(payload, Mapping) or len(payload) == 0
