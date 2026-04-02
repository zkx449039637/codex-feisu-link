from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import json
import os
import subprocess

from .models import ExecutionRequest, ExecutionResult, utc_now


@runtime_checkable
class ProcessLike(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


@runtime_checkable
class ProcessSpawner(Protocol):
    def __call__(self, command: list[str], **kwargs: Any) -> ProcessLike: ...


@dataclass(slots=True)
class ExecutionHandle:
    request: ExecutionRequest
    process: ProcessLike
    started_at: datetime
    log_file: Path
    artifact_dir: Path

    @property
    def pid(self) -> int | None:
        return getattr(self.process, "pid", None)

    def poll(self) -> int | None:
        return self.process.poll()

    def terminate(self) -> None:
        self.process.terminate()

    def kill(self) -> None:
        self.process.kill()


class SubprocessCodexExecutor:
    """Launch a configured local Codex command under subprocess."""

    def __init__(self, spawner: ProcessSpawner | None = None) -> None:
        self._spawner = spawner or subprocess.Popen

    def start(self, request: ExecutionRequest) -> ExecutionHandle:
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        request.log_file.parent.mkdir(parents=True, exist_ok=True)
        request.prompt_file.parent.mkdir(parents=True, exist_ok=True)
        request.prompt_file.write_text(request.prompt, encoding="utf-8")
        (request.artifact_dir / "request.json").write_text(
            json.dumps(request.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

        env = os.environ.copy()
        env.update({key: str(value) for key, value in request.env.items()})
        env.setdefault("CODEX_FEISHU_LINK_TASK_ID", request.task_id)
        env.setdefault("CODEX_FEISHU_LINK_PROJECT", request.project)
        env.setdefault("CODEX_FEISHU_LINK_PROMPT_FILE", str(request.prompt_file))
        env.setdefault("CODEX_FEISHU_LINK_ARTIFACT_DIR", str(request.artifact_dir))
        env.setdefault("CODEX_FEISHU_LINK_LOG_FILE", str(request.log_file))
        env.setdefault("CODEX_FEISHU_LINK_WORKDIR", str(request.workdir))

        with request.log_file.open("a", encoding="utf-8", newline="") as log_handle:
            log_handle.write(f"[{utc_now().isoformat()}] launch: {' '.join(request.command)}\n")
            log_handle.flush()
            kwargs: dict[str, Any] = {
                "cwd": str(request.workdir),
                "env": env,
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
                "text": True,
            }
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if creationflags:
                kwargs["creationflags"] = creationflags
            process = self._spawner(list(request.command), **kwargs)

        return ExecutionHandle(
            request=request,
            process=process,
            started_at=utc_now(),
            log_file=request.log_file,
            artifact_dir=request.artifact_dir,
        )

    def stop(self, handle: ExecutionHandle, *, force: bool = False, wait_seconds: float = 5.0) -> None:
        if handle.poll() is not None:
            return
        handle.terminate()
        if not force:
            return
        try:
            handle.process.wait(timeout=wait_seconds)
        except Exception:
            handle.kill()

    def finalize(
        self,
        handle: ExecutionHandle,
        *,
        returncode: int,
        finished_at: datetime | None = None,
        summary: str = "",
        error: str | None = None,
        canceled: bool = False,
    ) -> ExecutionResult:
        result = ExecutionResult(
            task_id=handle.request.task_id,
            project=handle.request.project,
            command=list(handle.request.command),
            returncode=returncode,
            started_at=handle.started_at,
            finished_at=finished_at or utc_now(),
            pid=handle.pid,
            log_file=handle.log_file,
            artifact_dir=handle.artifact_dir,
            summary=summary,
            error=error,
            canceled=canceled,
        )
        handle.artifact_dir.mkdir(parents=True, exist_ok=True)
        (handle.artifact_dir / "result.json").write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return result
