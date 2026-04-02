from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_task_id() -> str:
    return f"task_{uuid4().hex[:12]}"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class RuntimeStatus(str, Enum):
    IDLE = "idle"
    LAUNCHING = "launching"
    RUNNING = "running"
    STOPPING = "stopping"
    PAUSED = "paused"
    STOPPED = "stopped"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class ProjectConfig:
    name: str
    workdir: str
    branch_prefix: str = "codex/"
    description: str | None = None
    max_parallel_tasks: int = 1


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    project: str
    prompt: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    workdir: str | None = None
    branch: str | None = None
    summary: str = ""
    latest_log: str = ""
    requires_confirmation: bool = False
    pending_action: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        project: str,
        prompt: str,
        *,
        workdir: str | None = None,
        branch: str | None = None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> "TaskRecord":
        now = utc_now()
        return cls(
            task_id=task_id or new_task_id(),
            project=project,
            prompt=prompt,
            status=TaskStatus.QUEUED,
            created_at=now,
            updated_at=now,
            workdir=workdir,
            branch=branch,
            metadata=dict(metadata or {}),
        )

    def touch(self) -> None:
        self.updated_at = utc_now()

    def transition(self, status: TaskStatus) -> None:
        self.status = status
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project": self.project,
            "prompt": self.prompt,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "workdir": self.workdir,
            "branch": self.branch,
            "summary": self.summary,
            "latest_log": self.latest_log,
            "requires_confirmation": self.requires_confirmation,
            "pending_action": self.pending_action,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskRecord":
        return cls(
            task_id=data["task_id"],
            project=data["project"],
            prompt=data["prompt"],
            status=TaskStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            workdir=data.get("workdir"),
            branch=data.get("branch"),
            summary=data.get("summary", ""),
            latest_log=data.get("latest_log", ""),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            pending_action=data.get("pending_action"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class ExecutionRequest:
    task_id: str
    project: str
    command: list[str]
    workdir: Path
    prompt: str
    prompt_file: Path
    log_file: Path
    artifact_dir: Path
    env: dict[str, str] = field(default_factory=dict)
    stdin_text: str | None = None
    timeout_seconds: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project": self.project,
            "command": list(self.command),
            "workdir": str(self.workdir),
            "prompt": self.prompt,
            "prompt_file": str(self.prompt_file),
            "log_file": str(self.log_file),
            "artifact_dir": str(self.artifact_dir),
            "env": dict(self.env),
            "stdin_text": self.stdin_text,
            "timeout_seconds": self.timeout_seconds,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionRequest":
        return cls(
            task_id=data["task_id"],
            project=data["project"],
            command=list(data.get("command", [])),
            workdir=Path(str(data["workdir"])),
            prompt=data.get("prompt", ""),
            prompt_file=Path(str(data["prompt_file"])),
            log_file=Path(str(data["log_file"])),
            artifact_dir=Path(str(data["artifact_dir"])),
            env=dict(data.get("env", {})),
            stdin_text=data.get("stdin_text"),
            timeout_seconds=data.get("timeout_seconds"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class ExecutionResult:
    task_id: str
    project: str
    command: list[str]
    returncode: int
    started_at: datetime
    finished_at: datetime
    pid: int | None = None
    log_file: Path | None = None
    artifact_dir: Path | None = None
    summary: str = ""
    error: str | None = None
    canceled: bool = False

    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.canceled

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project": self.project,
            "command": list(self.command),
            "returncode": self.returncode,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "pid": self.pid,
            "log_file": str(self.log_file) if self.log_file is not None else None,
            "artifact_dir": str(self.artifact_dir) if self.artifact_dir is not None else None,
            "summary": self.summary,
            "error": self.error,
            "canceled": self.canceled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionResult":
        log_file = data.get("log_file")
        artifact_dir = data.get("artifact_dir")
        return cls(
            task_id=data["task_id"],
            project=data["project"],
            command=list(data.get("command", [])),
            returncode=int(data.get("returncode", 0)),
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]),
            pid=data.get("pid"),
            log_file=Path(str(log_file)) if log_file else None,
            artifact_dir=Path(str(artifact_dir)) if artifact_dir else None,
            summary=data.get("summary", ""),
            error=data.get("error"),
            canceled=bool(data.get("canceled", False)),
        )


@dataclass(slots=True)
class RuntimeTaskState:
    task_id: str
    project: str
    status: RuntimeStatus
    command: list[str] = field(default_factory=list)
    pid: int | None = None
    workdir: Path | None = None
    prompt_file: Path | None = None
    log_file: Path | None = None
    artifact_dir: Path | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_log_size: int = 0
    last_log_text: str = ""
    returncode: int | None = None
    summary: str = ""
    error: str | None = None
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project": self.project,
            "status": self.status.value,
            "command": list(self.command),
            "pid": self.pid,
            "workdir": str(self.workdir) if self.workdir is not None else None,
            "prompt_file": str(self.prompt_file) if self.prompt_file is not None else None,
            "log_file": str(self.log_file) if self.log_file is not None else None,
            "artifact_dir": str(self.artifact_dir) if self.artifact_dir is not None else None,
            "started_at": self.started_at.isoformat() if self.started_at is not None else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at is not None else None,
            "last_log_size": self.last_log_size,
            "last_log_text": self.last_log_text,
            "returncode": self.returncode,
            "summary": self.summary,
            "error": self.error,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeTaskState":
        workdir = data.get("workdir")
        prompt_file = data.get("prompt_file")
        log_file = data.get("log_file")
        artifact_dir = data.get("artifact_dir")
        started_at = data.get("started_at")
        finished_at = data.get("finished_at")
        return cls(
            task_id=data["task_id"],
            project=data["project"],
            status=RuntimeStatus(data.get("status", RuntimeStatus.IDLE.value)),
            command=list(data.get("command", [])),
            pid=data.get("pid"),
            workdir=Path(str(workdir)) if workdir else None,
            prompt_file=Path(str(prompt_file)) if prompt_file else None,
            log_file=Path(str(log_file)) if log_file else None,
            artifact_dir=Path(str(artifact_dir)) if artifact_dir else None,
            started_at=datetime.fromisoformat(started_at) if started_at else None,
            finished_at=datetime.fromisoformat(finished_at) if finished_at else None,
            last_log_size=int(data.get("last_log_size", 0)),
            last_log_text=data.get("last_log_text", ""),
            returncode=data.get("returncode"),
            summary=data.get("summary", ""),
            error=data.get("error"),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else utc_now(),
        )


@dataclass(slots=True)
class RuntimeState:
    version: int = 1
    updated_at: datetime = field(default_factory=utc_now)
    tasks: dict[str, RuntimeTaskState] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at.isoformat(),
            "tasks": {task_id: state.to_dict() for task_id, state in self.tasks.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeState":
        tasks = {
            task_id: RuntimeTaskState.from_dict(task_data)
            for task_id, task_data in dict(data.get("tasks", {})).items()
        }
        updated_at = data.get("updated_at")
        return cls(
            version=int(data.get("version", 1)),
            updated_at=datetime.fromisoformat(updated_at) if updated_at else utc_now(),
            tasks=tasks,
        )
