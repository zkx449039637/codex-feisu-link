from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from .config import ControllerConfig, ProjectConfig
from .models import TaskRecord, TaskStatus
from .storage import JsonStateStore, StateSnapshot


@dataclass(slots=True)
class SchedulerDecision:
    task: TaskRecord | None
    started: bool = False
    reason: str = ""


class TaskScheduler:
    def __init__(self, store: JsonStateStore, config: ControllerConfig) -> None:
        self.store = store
        self.config = config
        self._lock = RLock()

    def _project(self, project_name: str) -> ProjectConfig:
        try:
            return self.config.projects[project_name]
        except KeyError as exc:
            raise KeyError(f"Unknown project: {project_name}") from exc

    def list_projects(self) -> list[ProjectConfig]:
        return sorted(self.config.projects.values(), key=lambda project: project.name)

    def _sorted_project_tasks(self, snapshot: StateSnapshot, project_name: str) -> list[TaskRecord]:
        tasks = [task for task in snapshot.tasks.values() if task.project == project_name]
        return sorted(tasks, key=lambda task: (task.created_at, task.task_id))

    def _active_task(self, snapshot: StateSnapshot, project_name: str) -> TaskRecord | None:
        for task in self._sorted_project_tasks(snapshot, project_name):
            if task.status in {TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION, TaskStatus.PAUSED}:
                return task
        return None

    def _persist(self, mutator) -> StateSnapshot:
        with self._lock:
            return self.store.update(mutator)

    def enqueue(
        self,
        project_name: str,
        prompt: str,
        *,
        workdir: str | None = None,
        branch: str | None = None,
        metadata: dict | None = None,
        task_id: str | None = None,
    ) -> SchedulerDecision:
        project = self._project(project_name)

        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            task = TaskRecord.create(
                project=project.name,
                prompt=prompt,
                workdir=workdir or project.workdir,
                branch=branch,
                metadata=metadata,
                task_id=task_id,
            )
            snapshot.tasks[task.task_id] = task
            return snapshot

        snapshot = self._persist(mutator)
        task = snapshot.tasks[task_id] if task_id is not None else max(
            (task for task in snapshot.tasks.values() if task.project == project_name),
            key=lambda item: item.created_at,
        )
        if self._active_task(snapshot, project_name) is None:
            return self.admit_next_ready_task(project_name) or SchedulerDecision(task=task, reason="queued")
        return SchedulerDecision(task=task, reason="queued")

    def create_task(
        self,
        project_name: str,
        prompt: str,
        *,
        workdir: str | None = None,
        branch: str | None = None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> TaskRecord:
        return self.enqueue(
            project_name,
            prompt,
            workdir=workdir,
            branch=branch,
            metadata=metadata,
            task_id=task_id,
        ).task

    def admit_next_ready_task(self, project_name: str) -> SchedulerDecision | None:
        self._project(project_name)

        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            active = self._active_task(snapshot, project_name)
            if active is not None:
                return snapshot
            queued = self._sorted_project_tasks(snapshot, project_name)
            next_task = next((task for task in queued if task.status == TaskStatus.QUEUED), None)
            if next_task is None:
                return snapshot
            next_task.transition(TaskStatus.RUNNING)
            next_task.summary = "Task admitted to executor"
            return snapshot

        before = self.store.load()
        active_before = self._active_task(before, project_name)
        snapshot = self._persist(mutator)
        if active_before is not None:
            return None
        task = self._active_task(snapshot, project_name)
        if task is None or task.status != TaskStatus.RUNNING:
            return None
        return SchedulerDecision(task=task, started=True, reason="admitted")

    def list_tasks(self, project_name: str | None = None) -> list[TaskRecord]:
        snapshot = self.store.load()
        tasks = list(snapshot.tasks.values())
        if project_name is not None:
            tasks = [task for task in tasks if task.project == project_name]
        return sorted(tasks, key=lambda task: (task.project, task.created_at, task.task_id))

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self.store.load().tasks.get(task_id)

    def get_logs(self, task_id: str) -> str:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        return task.latest_log

    def get_diff(self, task_id: str) -> str:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        diff = task.metadata.get("diff")
        if isinstance(diff, str) and diff:
            return diff
        if task.summary:
            return task.summary
        return ""

    def update_log(self, task_id: str, message: str) -> TaskRecord:
        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            task = snapshot.tasks[task_id]
            task.latest_log = message
            task.touch()
            return snapshot

        snapshot = self._persist(mutator)
        return snapshot.tasks[task_id]

    def update_summary(self, task_id: str, summary: str) -> TaskRecord:
        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            task = snapshot.tasks[task_id]
            task.summary = summary
            task.touch()
            return snapshot

        snapshot = self._persist(mutator)
        return snapshot.tasks[task_id]

    def pause(self, task_id: str) -> TaskRecord:
        return self._transition(task_id, TaskStatus.PAUSED)

    def resume(self, task_id: str) -> TaskRecord:
        return self._transition(task_id, TaskStatus.RUNNING)

    def complete(self, task_id: str, *, summary: str | None = None) -> TaskRecord:
        return self._finalize(task_id, TaskStatus.COMPLETED, summary=summary)

    def fail(self, task_id: str, *, summary: str | None = None) -> TaskRecord:
        return self._finalize(task_id, TaskStatus.FAILED, summary=summary)

    def stop(self, task_id: str, *, summary: str | None = None) -> TaskRecord:
        return self._finalize(task_id, TaskStatus.STOPPED, summary=summary)

    def request_confirmation(self, task_id: str, action: str) -> TaskRecord:
        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            task = snapshot.tasks[task_id]
            task.status = TaskStatus.WAITING_CONFIRMATION
            task.requires_confirmation = True
            task.pending_action = action
            task.touch()
            return snapshot

        snapshot = self._persist(mutator)
        return snapshot.tasks[task_id]

    def confirm(self, task_id: str, approved: bool) -> TaskRecord:
        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            task = snapshot.tasks[task_id]
            if approved:
                task.requires_confirmation = False
                task.pending_action = None
                task.status = TaskStatus.RUNNING
            else:
                task.requires_confirmation = False
                task.pending_action = None
                task.status = TaskStatus.PAUSED
            task.touch()
            return snapshot

        snapshot = self._persist(mutator)
        return snapshot.tasks[task_id]

    def confirm_task(self, task_id: str, approved: bool, action: str | None = None) -> TaskRecord:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        if action is not None and task.requires_confirmation is False:
            self.request_confirmation(task_id, action)
        return self.confirm(task_id, approved)

    def continue_task(self, task_id: str, instruction: str) -> TaskRecord:
        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            task = snapshot.tasks[task_id]
            if instruction:
                task.metadata["follow_up_instruction"] = instruction
                if task.prompt:
                    task.prompt = f"{task.prompt}\n\nFollow-up instruction: {instruction}"
                else:
                    task.prompt = instruction
            if task.status in {TaskStatus.QUEUED, TaskStatus.PAUSED, TaskStatus.WAITING_CONFIRMATION}:
                task.status = TaskStatus.RUNNING
            task.touch()
            return snapshot

        snapshot = self._persist(mutator)
        task = snapshot.tasks[task_id]
        if task.status == TaskStatus.RUNNING:
            self.admit_next_ready_task(task.project)
        return task

    def snapshot_task(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        return {
            "task_id": task.task_id,
            "project": task.project,
            "status": task.status.value,
            "prompt": task.prompt,
            "workdir": task.workdir,
            "branch": task.branch,
            "summary": task.summary,
            "logs": task.latest_log,
            "diff": self.get_diff(task_id),
            "requires_confirmation": task.requires_confirmation,
            "pending_action": task.pending_action,
            "metadata": dict(task.metadata),
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }

    def _transition(self, task_id: str, status: TaskStatus) -> TaskRecord:
        def mutator(snapshot: StateSnapshot) -> StateSnapshot:
            task = snapshot.tasks[task_id]
            task.transition(status)
            return snapshot

        snapshot = self._persist(mutator)
        return snapshot.tasks[task_id]

    def _finalize(self, task_id: str, status: TaskStatus, *, summary: str | None = None) -> TaskRecord:
        task = self._transition(task_id, status)
        if summary is not None:
            task = self.update_summary(task_id, summary)
        self.admit_next_ready_task(task.project)
        return task
