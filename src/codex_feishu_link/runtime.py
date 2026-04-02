from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
import json
import tempfile
import time

from .config import ControllerConfig
from .executor import ExecutionHandle, SubprocessCodexExecutor
from .models import (
    ExecutionRequest,
    ExecutionResult,
    RuntimeState,
    RuntimeStatus,
    RuntimeTaskState,
    TaskRecord,
    TaskStatus,
    utc_now,
)


@dataclass(slots=True)
class RuntimePaths:
    root: Path
    logs: Path
    artifacts: Path
    state_file: Path


class JsonRuntimeStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> RuntimeState:
        if not self.path.exists():
            return RuntimeState()
        return RuntimeState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: RuntimeState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(self.path.parent),
            prefix=f"{self.path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    def update(self, mutator) -> RuntimeState:
        state = self.load()
        result = mutator(state)
        if isinstance(result, RuntimeState):
            state = result
        self.save(state)
        return state


class LocalCodexRuntime:
    """Poll scheduler tasks and run accepted work through a local Codex CLI."""

    def __init__(
        self,
        scheduler: Any,
        config: ControllerConfig,
        *,
        executor: SubprocessCodexExecutor | None = None,
        state_store: JsonRuntimeStateStore | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.config = config
        self.executor = executor or SubprocessCodexExecutor()
        self.state_store = state_store or JsonRuntimeStateStore(self._resolve_paths().state_file)
        self._handles: dict[str, ExecutionHandle] = {}
        self._lock = RLock()

    def _resolve_paths(self) -> RuntimePaths:
        root = self.config.runtime_root
        logs = self.config.runtime_log_dir or (root / "logs")
        artifacts = self.config.runtime_artifact_dir or (root / "artifacts")
        state_file = self.config.runtime_state_file or (root / "runtime-state.json")
        return RuntimePaths(root=root, logs=logs, artifacts=artifacts, state_file=state_file)

    def _project(self, project_name: str):
        return self.scheduler.config.projects[project_name]

    def _state(self) -> RuntimeState:
        return self.state_store.load()

    def _save_state(self, state: RuntimeState) -> None:
        state.touch()
        self.state_store.save(state)

    def _artifact_dir(self, task: TaskRecord) -> Path:
        paths = self._resolve_paths()
        return paths.artifacts / task.project / task.task_id

    def _log_file(self, task: TaskRecord) -> Path:
        return self._resolve_paths().logs / task.project / f"{task.task_id}.log"

    def _prompt_file(self, task: TaskRecord) -> Path:
        return self._artifact_dir(task) / "prompt.txt"

    def _build_command(self, task: TaskRecord) -> list[str]:
        metadata_command = task.metadata.get("command")
        if isinstance(metadata_command, list) and metadata_command:
            return [str(part) for part in metadata_command if str(part)]
        return [self.config.codex_executable, *self.config.codex_arguments]

    def _build_request(self, task: TaskRecord) -> ExecutionRequest:
        project = self._project(task.project)
        workdir = Path(task.workdir or project.workdir)
        artifact_dir = self._artifact_dir(task)
        log_file = self._log_file(task)
        prompt_file = self._prompt_file(task)
        command = self._build_command(task)
        env = {
            "CODEX_FEISHU_LINK_TASK_ID": task.task_id,
            "CODEX_FEISHU_LINK_PROJECT": task.project,
            "CODEX_FEISHU_LINK_WORKDIR": str(workdir),
            "CODEX_FEISHU_LINK_PROMPT_FILE": str(prompt_file),
            "CODEX_FEISHU_LINK_ARTIFACT_DIR": str(artifact_dir),
            "CODEX_FEISHU_LINK_LOG_FILE": str(log_file),
        }
        extra_env = task.metadata.get("env")
        if isinstance(extra_env, dict):
            for key, value in extra_env.items():
                env[str(key)] = str(value)
        return ExecutionRequest(
            task_id=task.task_id,
            project=task.project,
            command=command,
            workdir=workdir,
            prompt=task.prompt,
            prompt_file=prompt_file,
            log_file=log_file,
            artifact_dir=artifact_dir,
            env=env,
            stdin_text=task.metadata.get("stdin_text") if isinstance(task.metadata.get("stdin_text"), str) else None,
            timeout_seconds=self.config.command_timeout_seconds,
            metadata=dict(task.metadata),
        )

    def _read_log_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _tail_summary(self, text: str, *, max_lines: int = 8) -> str:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        tail = lines[-max_lines:]
        return "\n".join(tail)

    def _update_log(self, task_id: str, text: str) -> None:
        if text:
            self.scheduler.update_log(task_id, text)

    def _update_summary(self, task_id: str, summary: str) -> None:
        if summary:
            self.scheduler.update_summary(task_id, summary)

    def _launch_ready_tasks(self, state: RuntimeState) -> None:
        for project in self.scheduler.list_projects():
            active = sum(
                1
                for handle in self._handles.values()
                if handle.request.project == project.name and handle.poll() is None
            )
            if active >= project.max_parallel_tasks:
                continue
            for task in self.scheduler.list_tasks(project.name):
                if task.status != TaskStatus.RUNNING:
                    continue
                runtime_entry = state.tasks.get(task.task_id)
                if runtime_entry is not None and runtime_entry.status in {
                    RuntimeStatus.LAUNCHING,
                    RuntimeStatus.RUNNING,
                    RuntimeStatus.STOPPING,
                }:
                    continue
                if task.task_id in self._handles:
                    continue
                if active >= project.max_parallel_tasks:
                    break
                handle = self._start_task(task, state)
                if handle is not None:
                    active += 1

    def _start_task(self, task: TaskRecord, state: RuntimeState) -> ExecutionHandle | None:
        request = self._build_request(task)
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        request.log_file.parent.mkdir(parents=True, exist_ok=True)
        request.prompt_file.parent.mkdir(parents=True, exist_ok=True)
        request.prompt_file.write_text(task.prompt, encoding="utf-8")
        (request.artifact_dir / "request.json").write_text(
            json.dumps(request.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

        runtime_entry = RuntimeTaskState(
            task_id=task.task_id,
            project=task.project,
            status=RuntimeStatus.LAUNCHING,
            command=list(request.command),
            workdir=request.workdir,
            prompt_file=request.prompt_file,
            log_file=request.log_file,
            artifact_dir=request.artifact_dir,
            started_at=utc_now(),
        )
        state.tasks[task.task_id] = runtime_entry
        self._save_state(state)
        self._update_summary(task.task_id, f"Launching {' '.join(request.command)}")
        self._update_log(task.task_id, f"Launching task {task.task_id} in {request.workdir}\n")

        try:
            handle = self.executor.start(request)
        except Exception as exc:
            runtime_entry.status = RuntimeStatus.FAILED
            runtime_entry.error = str(exc)
            runtime_entry.finished_at = utc_now()
            runtime_entry.touch()
            self._save_state(state)
            self.scheduler.fail(task.task_id, summary=f"Launch failed: {exc}")
            return None

        runtime_entry.status = RuntimeStatus.RUNNING
        runtime_entry.pid = handle.pid
        runtime_entry.touch()
        self._handles[task.task_id] = handle
        self._save_state(state)
        return handle

    def _finalize_task(
        self,
        task: TaskRecord,
        handle: ExecutionHandle,
        state: RuntimeState,
        *,
        returncode: int,
        canceled: bool = False,
        error: str | None = None,
    ) -> ExecutionResult:
        log_text = self._read_log_text(handle.log_file)
        if log_text:
            self._update_log(task.task_id, log_text)
        summary = self._tail_summary(log_text) or f"Task exited with code {returncode}"
        if returncode == 0 and not canceled:
            self.scheduler.complete(task.task_id, summary=summary)
            final_status = RuntimeStatus.COMPLETED
        elif canceled:
            self.scheduler.update_summary(task.task_id, summary)
            if task.status == TaskStatus.PAUSED:
                final_status = RuntimeStatus.PAUSED
            elif task.status == TaskStatus.STOPPED:
                final_status = RuntimeStatus.STOPPED
            else:
                final_status = RuntimeStatus.WAITING_CONFIRMATION
        else:
            self.scheduler.fail(task.task_id, summary=summary)
            final_status = RuntimeStatus.FAILED

        result = self.executor.finalize(
            handle,
            returncode=returncode,
            summary=summary,
            error=error,
            canceled=canceled,
        )
        entry = state.tasks.get(task.task_id)
        if entry is None:
            entry = RuntimeTaskState(task_id=task.task_id, project=task.project, status=final_status)
            state.tasks[task.task_id] = entry
        entry.status = final_status
        entry.returncode = returncode
        entry.finished_at = utc_now()
        entry.summary = summary
        entry.error = error
        entry.last_log_text = log_text
        entry.last_log_size = len(log_text)
        entry.touch()
        self._save_state(state)
        return result

    def _poll_handle(self, task: TaskRecord, handle: ExecutionHandle, state: RuntimeState) -> ExecutionResult | None:
        task_status = task.status
        returncode = handle.poll()
        log_text = self._read_log_text(handle.log_file)
        entry = state.tasks.get(task.task_id)
        if entry is None:
            entry = RuntimeTaskState(task_id=task.task_id, project=task.project, status=RuntimeStatus.RUNNING)
            state.tasks[task.task_id] = entry
        if log_text and log_text != entry.last_log_text:
            entry.last_log_text = log_text
            entry.last_log_size = len(log_text)
            entry.touch()
            self._update_log(task.task_id, log_text)
            self._save_state(state)
        if returncode is None:
            if task_status in {TaskStatus.PAUSED, TaskStatus.STOPPED, TaskStatus.WAITING_CONFIRMATION}:
                if task_status == TaskStatus.PAUSED:
                    entry.status = RuntimeStatus.PAUSED
                elif task_status == TaskStatus.STOPPED:
                    entry.status = RuntimeStatus.STOPPED
                else:
                    entry.status = RuntimeStatus.WAITING_CONFIRMATION
                entry.touch()
                self._save_state(state)
                self.executor.stop(handle, force=True)
            return None

        self._handles.pop(task.task_id, None)
        return self._finalize_task(task, handle, state, returncode=returncode, canceled=task_status in {TaskStatus.PAUSED, TaskStatus.STOPPED, TaskStatus.WAITING_CONFIRMATION})

    def step(self) -> list[ExecutionResult]:
        with self._lock:
            state = self._state()
            results: list[ExecutionResult] = []
            for task_id, handle in list(self._handles.items()):
                task = self.scheduler.get_task(task_id)
                if task is None:
                    self._handles.pop(task_id, None)
                    continue
                result = self._poll_handle(task, handle, state)
                if result is not None:
                    results.append(result)
            self._launch_ready_tasks(state)
            self._save_state(state)
            return results

    def run_forever(self, *, stop_after: float | None = None) -> None:
        started = time.monotonic()
        while True:
            self.step()
            if stop_after is not None and time.monotonic() - started >= stop_after:
                return
            time.sleep(self.config.runtime_poll_interval_seconds)
