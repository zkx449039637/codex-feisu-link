"""Application service for the Feishu-controlled Codex CLI orchestrator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .commands import Command, CommandParseError, command_help, parse_command
from .feishu_adapter import FeishuEventAdapter, FeishuMessageEvent


@dataclass(frozen=True, slots=True)
class CommandContext:
    sender_id: str | None = None
    chat_id: str | None = None
    message_id: str | None = None


@runtime_checkable
class SchedulerBackend(Protocol):
    def list_projects(self) -> Sequence[Any]: ...
    def list_tasks(self, project: str | None = None) -> Sequence[Any]: ...
    def create_task(self, project: str, description: str) -> Any: ...
    def get_task(self, task_id: str) -> Any: ...
    def get_logs(self, task_id: str) -> Any: ...
    def get_diff(self, task_id: str) -> Any: ...
    def continue_task(self, task_id: str, instruction: str = "") -> Any: ...
    def pause_task(self, task_id: str) -> Any: ...
    def resume_task(self, task_id: str) -> Any: ...
    def stop_task(self, task_id: str) -> Any: ...
    def confirm_task(self, task_id: str, approved: bool) -> Any: ...
    def snapshot_task(self, task_id: str) -> Any: ...


class FeishuCodexApp:
    """Glue layer between Feishu messages and scheduler/storage operations."""

    def __init__(
        self,
        scheduler: Any | None = None,
        storage: Any | None = None,
        adapter: FeishuEventAdapter | None = None,
        allowed_sender_ids: set[str] | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.storage = storage
        self.adapter = adapter or FeishuEventAdapter()
        self.allowed_sender_ids = allowed_sender_ids

    def handle_payload(self, payload: Mapping[str, Any]) -> str | None:
        message = self.adapter.extract_message(payload)
        if message is None:
            return None
        return self.handle_message(message)

    def handle_text(self, text: str, sender_id: str | None = None, chat_id: str | None = None, message_id: str | None = None) -> str:
        return self.handle_message(
            FeishuMessageEvent(
                sender_id=sender_id,
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                raw={"text": text},
            )
        )

    def handle_message(self, message: FeishuMessageEvent) -> str:
        if self.allowed_sender_ids is not None and message.sender_id not in self.allowed_sender_ids:
            return "This bot is restricted to approved senders."

        try:
            command = parse_command(message.text)
        except CommandParseError as exc:
            return f"Parse error: {exc}\n{command_help()}"

        return self.dispatch(command, CommandContext(sender_id=message.sender_id, chat_id=message.chat_id, message_id=message.message_id))

    def dispatch_command_text(self, text: str, context: CommandContext | None = None) -> str:
        try:
            command = parse_command(text)
        except CommandParseError as exc:
            return f"Parse error: {exc}\n{command_help()}"
        return self.dispatch(command, context)

    def dispatch(self, command: Command, context: CommandContext | None = None) -> str:
        name = command.name
        if name == "projects":
            return self._render_projects(self._call_backend("list_projects"))
        if name == "tasks":
            return self._render_tasks(self._call_backend("list_tasks", command.project))
        if name == "new":
            return self._render_entity(self._call_backend("create_task", command.project, command.text))
        if name == "status":
            return self._render_entity(self._call_backend("get_task", command.task_id))
        if name == "logs":
            return self._render_value(self._call_backend("get_logs", command.task_id))
        if name == "diff":
            return self._render_value(self._call_backend("get_diff", command.task_id))
        if name == "continue":
            return self._render_entity(self._call_backend("continue_task", command.task_id, command.text))
        if name == "pause":
            return self._render_entity(self._call_backend("pause_task", command.task_id))
        if name == "resume":
            return self._render_entity(self._call_backend("resume_task", command.task_id))
        if name == "stop":
            return self._render_entity(self._call_backend("stop_task", command.task_id))
        if name == "confirm":
            return self._render_entity(self._call_backend("confirm_task", command.task_id, command.decision))
        if name == "snapshot":
            return self._render_value(self._call_backend("snapshot_task", command.task_id))
        return f"Unsupported command: {name}"

    def _call_backend(self, method: str, *args: Any) -> Any:
        if self.scheduler is None:
            return f"Backend not configured for `{method}`."
        target = getattr(self.scheduler, method, None)
        if target is None or not callable(target):
            return f"Scheduler does not expose `{method}`."
        return target(*args)

    def _render_projects(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        items = self._normalize_sequence(result)
        if not items:
            return "No projects found."
        lines = ["Projects:"]
        lines.extend(f"- {self._render_entity_line(item)}" for item in items)
        return "\n".join(lines)

    def _render_tasks(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        items = self._normalize_sequence(result)
        if not items:
            return "No tasks found."
        lines = ["Tasks:"]
        lines.extend(f"- {self._render_entity_line(item)}" for item in items)
        return "\n".join(lines)

    def _render_entity(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        return self._render_entity_line(result)

    def _render_value(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if result is None:
            return "No data."
        if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
            if not result:
                return "No data."
            return "\n".join(str(item) for item in result)
        return str(result)

    def _normalize_sequence(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (str, bytes, bytearray)):
            return [value]
        if isinstance(value, Sequence):
            return list(value)
        return [value]

    def _render_entity_line(self, item: Any) -> str:
        data = self._entity_to_mapping(item)
        if not data:
            return str(item)

        preferred_keys = ("task_id", "id", "project_id", "name", "status", "branch")
        parts = []
        for key in preferred_keys:
            value = data.get(key)
            if value not in (None, ""):
                parts.append(f"{key}={value}")
        remaining = [f"{key}={value}" for key, value in data.items() if key not in preferred_keys and value not in (None, "")]
        if parts or remaining:
            return ", ".join(parts + remaining)
        return str(item)

    def _entity_to_mapping(self, item: Any) -> dict[str, Any]:
        if isinstance(item, Mapping):
            return dict(item)
        if is_dataclass(item):
            return asdict(item)
        attrs = {}
        for key in ("task_id", "id", "project_id", "name", "status", "branch", "description", "summary"):
            if hasattr(item, key):
                attrs[key] = getattr(item, key)
        return attrs
