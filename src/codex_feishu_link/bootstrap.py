from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
import argparse
from threading import Event, Thread

from .app import FeishuCodexApp
from .commands import command_help
from .config import ControllerConfig, load_controller_config
from .feishu_long_connection_sdk import FeishuSdkConfig, build_sdk_service_runtime, load_feishu_sdk_config
from .runtime import LocalCodexRuntime
from .scheduler import TaskScheduler
from .storage import JsonStateStore


class RuntimeExecutor(Protocol):
    def start(self, scheduler: TaskScheduler) -> None: ...

    def stop(self) -> None: ...


class TransportRuntime(Protocol):
    def run(self, handler: Callable[[Mapping[str, Any]], str | None]) -> int | None: ...


class BackgroundRuntimeExecutor:
    def __init__(self, runtime: LocalCodexRuntime) -> None:
        self.runtime = runtime
        self._thread: Thread | None = None
        self._stop_flag = Event()

    def start(self, scheduler: TaskScheduler) -> None:
        if scheduler is not self.runtime.scheduler:
            self.runtime.scheduler = scheduler
        self._stop_flag.clear()
        self._thread = Thread(target=self._run_loop, name="codex-feishu-runtime", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        while not self._stop_flag.is_set():
            self.runtime.step()
            if self._stop_flag.wait(self.runtime.config.runtime_poll_interval_seconds):
                break

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=self.runtime.config.runtime_poll_interval_seconds * 2)


@dataclass(slots=True)
class BootstrapBundle:
    config: ControllerConfig
    store: JsonStateStore
    scheduler: TaskScheduler
    app: FeishuCodexApp
    executor: RuntimeExecutor | None = None
    transport: TransportRuntime | None = None
    sdk_config: FeishuSdkConfig | None = None
    sdk_module: Any | None = None
    sdk_client: Any | None = None
    service_stop_after: int | None = None

    def run(self, mode: str = "local") -> int:
        normalized = mode.lower().strip()
        if normalized == "local":
            return self.run_local_repl()
        if normalized == "service":
            return self.run_service()
        raise ValueError(f"Unsupported bootstrap mode: {mode}")

    def run_local_repl(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> int:
        output_fn(command_help())
        output_fn("Enter a command, or press Ctrl+C / Ctrl+D to exit.")
        while True:
            try:
                line = input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt):
                output_fn("")
                return 0
            if not line:
                continue
            output_fn(self.app.dispatch_command_text(line))

    def run_service(self) -> int:
        transport = self.transport or self._build_default_transport()
        executor = self.executor or self._build_default_executor()

        executor.start(self.scheduler)
        try:
            result = transport.run(self.app.handle_payload)
            if result is None:
                return 0
            if isinstance(result, int):
                return result
            return int(result)
        finally:
            stop_transport = getattr(transport, "stop", None)
            if callable(stop_transport):
                stop_transport()
            executor.stop()

    def _build_default_executor(self) -> BackgroundRuntimeExecutor:
        runtime = LocalCodexRuntime(self.scheduler, self.config)
        return BackgroundRuntimeExecutor(runtime)

    def _build_default_transport(self) -> TransportRuntime:
        sdk_config = self.sdk_config or self._sdk_config_from_controller_config()
        runtime = build_sdk_service_runtime(
            self.app,
            sdk_config=sdk_config,
            sdk_module=self.sdk_module,
            sdk_client=self.sdk_client,
            stop_after=self.service_stop_after,
        )
        if runtime is None:
            raise RuntimeError(
                "Service mode requires FEISHU_APP_ID / FEISHU_APP_SECRET and a compatible Feishu SDK client."
        )
        return runtime

    def _sdk_config_from_controller_config(self) -> FeishuSdkConfig | None:
        if self.config.feishu_app_id is None or self.config.feishu_app_secret is None:
            return load_feishu_sdk_config()
        return FeishuSdkConfig(
            app_id=self.config.feishu_app_id,
            app_secret=self.config.feishu_app_secret,
            base_url=self.config.feishu_base_url,
            receive_id_type=self.config.feishu_receive_id_type,
        )


def build_bootstrap(
    config_path: str | Path | None = None,
    *,
    allowed_sender_ids: set[str] | None = None,
    executor: RuntimeExecutor | None = None,
    transport: TransportRuntime | None = None,
    sdk_config: FeishuSdkConfig | None = None,
    sdk_module: Any | None = None,
    sdk_client: Any | None = None,
    service_stop_after: int | None = None,
) -> BootstrapBundle:
    config = load_controller_config(config_path)
    store = JsonStateStore(config.state_file)
    scheduler = TaskScheduler(store, config)
    app = FeishuCodexApp(
        scheduler=scheduler,
        storage=store,
        allowed_sender_ids=allowed_sender_ids if allowed_sender_ids is not None else (config.allowed_user_ids or None),
    )
    return BootstrapBundle(
        config=config,
        store=store,
        scheduler=scheduler,
        app=app,
        executor=executor,
        transport=transport,
        sdk_config=sdk_config,
        sdk_module=sdk_module,
        sdk_client=sdk_client,
        service_stop_after=service_stop_after,
    )


def bootstrap(
    config_path: str | Path | None = None,
    *,
    mode: str = "local",
    allowed_sender_ids: set[str] | None = None,
    executor: RuntimeExecutor | None = None,
    transport: TransportRuntime | None = None,
    sdk_config: FeishuSdkConfig | None = None,
    sdk_module: Any | None = None,
    sdk_client: Any | None = None,
    service_stop_after: int | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    bundle = build_bootstrap(
        config_path,
        allowed_sender_ids=allowed_sender_ids,
        executor=executor,
        transport=transport,
        sdk_config=sdk_config,
        sdk_module=sdk_module,
        sdk_client=sdk_client,
        service_stop_after=service_stop_after,
    )
    if mode.lower().strip() == "local":
        return bundle.run_local_repl(input_fn=input_fn, output_fn=output_fn)
    return bundle.run(mode=mode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Codex Feishu controller.")
    parser.add_argument("--config", dest="config_path", help="Path to JSON or TOML controller config.")
    parser.add_argument(
        "--mode",
        choices=("local", "service"),
        default="local",
        help="Local mode starts the REPL; service mode uses injected transport/executor runtimes.",
    )
    return parser.parse_args(argv)
