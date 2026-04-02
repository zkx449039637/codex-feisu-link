from __future__ import annotations

import json
import shutil
import os
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.app import FeishuCodexApp  # noqa: E402
from codex_feishu_link.config import ControllerConfig, ProjectConfig  # noqa: E402
from codex_feishu_link.feishu_adapter import FeishuEventAdapter  # noqa: E402
from codex_feishu_link.models import TaskStatus  # noqa: E402
from codex_feishu_link.scheduler import TaskScheduler  # noqa: E402
from codex_feishu_link.storage import JsonStateStore  # noqa: E402


@dataclass
class ProjectView:
    name: str
    workdir: str
    branch_prefix: str = "codex/"
    max_parallel_tasks: int = 1


class FakeBackend:
    def __init__(self) -> None:
        self.projects = [ProjectView(name="alpha", workdir=r"D:\\alpha")]
        self.tasks: dict[str, dict[str, object]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._next_id = 1

    def list_projects(self):
        self.calls.append(("list_projects", ()))
        return self.projects

    def list_tasks(self, project: str | None = None):
        self.calls.append(("list_tasks", (project,)))
        tasks = list(self.tasks.values())
        if project is not None:
            tasks = [task for task in tasks if task["project"] == project]
        return tasks

    def create_task(self, project: str, description: str):
        self.calls.append(("create_task", (project, description)))
        task_id = f"T{self._next_id}"
        self._next_id += 1
        task = {
            "task_id": task_id,
            "project": project,
            "description": description,
            "status": "running" if len(self.tasks) == 0 else "queued",
            "branch": f"codex/{task_id.lower()}",
        }
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str):
        self.calls.append(("get_task", (task_id,)))
        return self.tasks[task_id]

    def get_logs(self, task_id: str):
        self.calls.append(("get_logs", (task_id,)))
        return f"log for {task_id}"

    def get_diff(self, task_id: str):
        self.calls.append(("get_diff", (task_id,)))
        return f"diff for {task_id}"

    def continue_task(self, task_id: str, instruction: str = ""):
        self.calls.append(("continue_task", (task_id, instruction)))
        task = self.tasks[task_id]
        task["description"] = instruction or task["description"]
        return task

    def pause_task(self, task_id: str):
        self.calls.append(("pause_task", (task_id,)))
        task = self.tasks[task_id]
        task["status"] = "paused"
        return task

    def resume_task(self, task_id: str):
        self.calls.append(("resume_task", (task_id,)))
        task = self.tasks[task_id]
        task["status"] = "running"
        return task

    def stop_task(self, task_id: str):
        self.calls.append(("stop_task", (task_id,)))
        task = self.tasks[task_id]
        task["status"] = "stopped"
        return task

    def confirm_task(self, task_id: str, approved: bool):
        self.calls.append(("confirm_task", (task_id, approved)))
        task = self.tasks[task_id]
        task["confirmed"] = approved
        task["status"] = "running" if approved else "paused"
        return task

    def snapshot_task(self, task_id: str):
        self.calls.append(("snapshot_task", (task_id,)))
        return {"task_id": task_id, "status": self.tasks[task_id]["status"]}


class SchedulerFacade:
    def __init__(self, scheduler: TaskScheduler) -> None:
        self.scheduler = scheduler

    def list_projects(self):
        return [
            ProjectView(
                name=project.name,
                workdir=project.workdir,
                branch_prefix=project.branch_prefix,
                max_parallel_tasks=project.max_parallel_tasks,
            )
            for project in self.scheduler.config.projects.values()
        ]

    def list_tasks(self, project: str | None = None):
        return self.scheduler.list_tasks(project)

    def create_task(self, project: str, description: str):
        decision = self.scheduler.enqueue(project, description)
        assert decision.task is not None
        return self.scheduler.get_task(decision.task.task_id)

    def get_task(self, task_id: str):
        return self.scheduler.get_task(task_id)

    def get_logs(self, task_id: str):
        task = self.scheduler.get_task(task_id)
        return task.latest_log or f"No logs for {task_id}"

    def get_diff(self, task_id: str):
        task = self.scheduler.get_task(task_id)
        return f"{task.task_id}: {task.prompt}"

    def continue_task(self, task_id: str, instruction: str = ""):
        return self.scheduler.update_summary(task_id, instruction or "continued")

    def pause_task(self, task_id: str):
        return self.scheduler.pause(task_id)

    def resume_task(self, task_id: str):
        return self.scheduler.resume(task_id)

    def stop_task(self, task_id: str):
        return self.scheduler.stop(task_id)

    def confirm_task(self, task_id: str, approved: bool):
        return self.scheduler.confirm(task_id, approved)

    def snapshot_task(self, task_id: str):
        task = self.scheduler.get_task(task_id)
        return {
            "task_id": task.task_id,
            "project": task.project,
            "status": task.status.value,
            "summary": task.summary,
        }


class FeishuAppIntegrationTests(unittest.TestCase):
    def test_handle_payload_routes_through_adapter_and_fake_backend(self) -> None:
        backend = FakeBackend()
        app = FeishuCodexApp(scheduler=backend, allowed_sender_ids={"user-1"})
        payload = {
            "event": {
                "sender": {"sender_id": "user-1"},
                "message": {
                    "chat_id": "chat-1",
                    "message_id": "msg-1",
                    "content": json.dumps({"text": "projects"}),
                },
            }
        }

        reply = app.handle_payload(payload)

        self.assertEqual(reply, "Projects:\n- name=alpha, workdir=D:\\\\alpha, branch_prefix=codex/, max_parallel_tasks=1")
        self.assertEqual(backend.calls[0][0], "list_projects")

    def test_sender_restriction_blocks_unauthorized_users(self) -> None:
        backend = FakeBackend()
        app = FeishuCodexApp(scheduler=backend, allowed_sender_ids={"trusted"})

        reply = app.handle_text("projects", sender_id="intruder")

        self.assertEqual(reply, "This bot is restricted to approved senders.")
        self.assertEqual(backend.calls, [])

    def test_public_app_layer_with_real_scheduler_backend(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".test_tmp" / f"app_{os.getpid()}_{uuid4().hex}"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = JsonStateStore(workspace_tmp / "state.json")
            config = ControllerConfig(
                state_file=store.path,
                projects={"alpha": ProjectConfig(name="alpha", workdir=r"D:\\alpha")},
            )
            scheduler = TaskScheduler(store, config)
            app = FeishuCodexApp(scheduler=SchedulerFacade(scheduler))

            first_reply = app.dispatch_command_text("new alpha ship login flow")
            second_reply = app.dispatch_command_text("new alpha add tests")

            self.assertIn("task_id=", first_reply)
            self.assertIn("project=alpha", first_reply)
            self.assertIn(f"status={TaskStatus.RUNNING}", first_reply)
            self.assertIn(f"status={TaskStatus.QUEUED}", second_reply)

            tasks_reply = app.dispatch_command_text("tasks alpha")
            self.assertIn("Tasks:", tasks_reply)
            self.assertIn("project=alpha", tasks_reply)
            self.assertIn(f"status={TaskStatus.RUNNING}", tasks_reply)
            self.assertIn(f"status={TaskStatus.QUEUED}", tasks_reply)

            first_task_id = scheduler.list_tasks("alpha")[0].task_id
            stop_reply = app.dispatch_command_text(f"stop {first_task_id}")
            self.assertIn(f"status={TaskStatus.STOPPED}", stop_reply)

            refreshed_tasks = scheduler.list_tasks("alpha")
            self.assertEqual(refreshed_tasks[0].status, TaskStatus.STOPPED)
            self.assertEqual(refreshed_tasks[1].status, TaskStatus.RUNNING)

            snapshot_reply = app.dispatch_command_text(f"snapshot {refreshed_tasks[1].task_id}")
            self.assertIn(refreshed_tasks[1].task_id, snapshot_reply)
        finally:
            shutil.rmtree(workspace_tmp, ignore_errors=True)

    def test_adapter_extracts_text_messages(self) -> None:
        adapter = FeishuEventAdapter()
        payload = {
            "event": {
                "sender": {"sender_id": "user-1"},
                "message": {"chat_id": "chat-1", "message_id": "msg-1", "text": "status T1024"},
            }
        }

        message = adapter.extract_message(payload)

        self.assertIsNotNone(message)
        self.assertEqual(message.text, "status T1024")
        self.assertEqual(message.chat_id, "chat-1")
        self.assertEqual(message.message_id, "msg-1")


if __name__ == "__main__":
    unittest.main()
