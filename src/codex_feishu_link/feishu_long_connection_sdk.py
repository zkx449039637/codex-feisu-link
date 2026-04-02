from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from importlib import import_module
import inspect
from threading import Event, Lock, Thread
from types import ModuleType
from typing import Any, Callable, Mapping
import json
import os

from .app import FeishuCodexApp
from .feishu_adapter import FeishuEventAdapter, FeishuMessageEvent
from .feishu_http_client import FeishuHttpClient


@dataclass(frozen=True, slots=True)
class FeishuSdkConfig:
    app_id: str
    app_secret: str
    base_url: str = "https://open.feishu.cn"
    sdk_module_name: str = "lark_oapi"
    receive_id_type: str = "chat_id"
    poll_timeout_seconds: float = 1.0
    idle_sleep_seconds: float = 0.5


@dataclass(frozen=True, slots=True)
class FeishuSdkTransportResult:
    outcome: str
    response_payload: dict[str, Any] | None = None
    reply_text: str | None = None


@dataclass(slots=True)
class FeishuSdkEventHandler:
    app: FeishuCodexApp
    message_sender: Any
    receive_id_type: str = "chat_id"
    on_event_processed: Callable[[], None] | None = None
    adapter: FeishuEventAdapter = field(default_factory=FeishuEventAdapter)

    def do_without_validation(self, payload: bytes) -> None:
        try:
            event_payload = json.loads(payload.decode("utf-8"))
        except Exception:
            return None

        if not isinstance(event_payload, Mapping):
            return None

        message = self.adapter.extract_message(event_payload)
        if message is None:
            return None

        reply_text = self.app.handle_message(message)
        if reply_text:
            receive_id = self._resolve_receive_id(message)
            if receive_id:
                sender = getattr(self.message_sender, "send_text_message", None)
                if callable(sender):
                    sender(receive_id, reply_text, receive_id_type=self.receive_id_type)

        if self.on_event_processed is not None:
            self.on_event_processed()
        return None

    def _resolve_receive_id(self, message: FeishuMessageEvent) -> str | None:
        if self.receive_id_type == "sender_id":
            return message.sender_id or message.chat_id
        return message.chat_id or message.sender_id


@dataclass(slots=True)
class FeishuWsServiceRuntime:
    client: Any
    event_handler: FeishuSdkEventHandler
    poll_timeout_seconds: float = 1.0
    idle_sleep_seconds: float = 0.5
    stop_after: int | None = None
    _stop_flag: Event = field(default_factory=Event, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _thread: Thread | None = field(default=None, init=False, repr=False)
    _processed_events: int = field(default=0, init=False, repr=False)

    def run(self, handler: Callable[[Mapping[str, Any]], str | None]) -> int:
        del handler
        self._stop_flag.clear()
        self._thread = Thread(target=self._client_start, name="codex-feishu-sdk", daemon=True)
        self._thread.start()
        try:
            while True:
                if self._stop_flag.is_set():
                    break
                if self.stop_after is not None and self._event_count() >= self.stop_after:
                    self._stop_flag.set()
                    break
                if self._thread is not None and not self._thread.is_alive():
                    break
                self._stop_flag.wait(self.idle_sleep_seconds)
        finally:
            self.stop()
        return 0

    def stop(self) -> None:
        self._stop_flag.set()
        self._disconnect_client()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(self.idle_sleep_seconds * 2, 0.5))

    def _client_start(self) -> None:
        try:
            self.client.start()
        finally:
            self._stop_flag.set()

    def _record_event(self) -> None:
        with self._lock:
            self._processed_events += 1
            processed = self._processed_events
        if self.stop_after is not None and processed >= self.stop_after:
            self._stop_flag.set()

    def _event_count(self) -> int:
        with self._lock:
            return self._processed_events

    def _disconnect_client(self) -> None:
        for attr in ("stop", "close", "_disconnect"):
            disconnect = getattr(self.client, attr, None)
            if not callable(disconnect):
                continue
            try:
                result = disconnect()
                if inspect.isawaitable(result):
                    self._run_awaitable(result)
            except Exception:
                pass
            break

    def _run_awaitable(self, awaitable: Any) -> None:
        try:
            asyncio.run(awaitable)
            return
        except RuntimeError:
            pass

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(awaitable)
        finally:
            loop.close()


def load_feishu_sdk_config(env: Mapping[str, str] | None = None) -> FeishuSdkConfig | None:
    values = env or os.environ
    app_id = values.get("CODEX_FEISHU_LINK_APP_ID") or values.get("FEISHU_APP_ID")
    app_secret = values.get("CODEX_FEISHU_LINK_APP_SECRET") or values.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        return None
    return FeishuSdkConfig(
        app_id=app_id,
        app_secret=app_secret,
        base_url=values.get("CODEX_FEISHU_LINK_FEISHU_BASE_URL", "https://open.feishu.cn"),
        sdk_module_name=values.get("CODEX_FEISHU_LINK_SDK_MODULE", "lark_oapi"),
        receive_id_type=values.get("CODEX_FEISHU_LINK_RECEIVE_ID_TYPE", "chat_id"),
        poll_timeout_seconds=float(values.get("CODEX_FEISHU_LINK_SDK_POLL_TIMEOUT_SECONDS", "1.0")),
        idle_sleep_seconds=float(values.get("CODEX_FEISHU_LINK_SDK_IDLE_SLEEP_SECONDS", "0.5")),
    )


def load_official_sdk_module(module_name: str) -> ModuleType | None:
    try:
        return import_module(module_name)
    except ImportError:
        return None


def build_official_sdk_client(
    config: FeishuSdkConfig,
    *,
    sdk_module: ModuleType | None = None,
    event_handler: Any | None = None,
) -> Any | None:
    module = sdk_module or load_official_sdk_module(config.sdk_module_name)
    if module is None:
        return None

    ws_module = getattr(module, "ws", None)
    client_type = getattr(ws_module, "Client", None) if ws_module is not None else None
    if client_type is None:
        raise RuntimeError(
            f"Found Feishu SDK module `{module.__name__}` but could not locate `ws.Client`."
        )

    try:
        return client_type(
            config.app_id,
            config.app_secret,
            event_handler=event_handler,
            domain=config.base_url,
        )
    except TypeError as exc:
        raise RuntimeError(
            f"Failed to construct `ws.Client` from `{module.__name__}`."
        ) from exc


def build_sdk_service_runtime(
    app: FeishuCodexApp,
    *,
    sdk_config: FeishuSdkConfig | None = None,
    sdk_module: ModuleType | None = None,
    sdk_client: Any | None = None,
    message_sender: Any | None = None,
    stop_after: int | None = None,
) -> FeishuWsServiceRuntime | None:
    config = sdk_config or load_feishu_sdk_config()
    if config is None:
        return None

    sender = message_sender or FeishuHttpClient(
        config.app_id,
        config.app_secret,
        base_url=config.base_url,
        receive_id_type=config.receive_id_type,
    )
    event_handler = FeishuSdkEventHandler(
        app=app,
        message_sender=sender,
        receive_id_type=config.receive_id_type,
    )

    client = sdk_client
    if client is None:
        client = build_official_sdk_client(
            config,
            sdk_module=sdk_module,
            event_handler=event_handler,
        )
    if client is None:
        return None

    if getattr(client, "event_handler", None) is None:
        try:
            setattr(client, "event_handler", event_handler)
        except Exception:
            pass
    if getattr(client, "_event_handler", None) is None:
        try:
            setattr(client, "_event_handler", event_handler)
        except Exception:
            pass

    runtime = FeishuWsServiceRuntime(
        client=client,
        event_handler=event_handler,
        poll_timeout_seconds=config.poll_timeout_seconds,
        idle_sleep_seconds=config.idle_sleep_seconds,
        stop_after=stop_after,
    )
    event_handler.on_event_processed = runtime._record_event
    return runtime
