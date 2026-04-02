from __future__ import annotations

from pathlib import Path
import sys
import unittest
import shutil
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.config import ControllerConfig, ProjectConfig
from codex_feishu_link.models import TaskStatus
from codex_feishu_link.scheduler import TaskScheduler
from codex_feishu_link.storage import JsonStateStore


class SchedulerTests(unittest.TestCase):
    def test_enqueue_and_single_writer_admit(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp = workspace_tmp / f"scheduler-{uuid.uuid4().hex}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = JsonStateStore(Path(tmp) / "state.json")
            config = ControllerConfig(
                state_file=store.path,
                projects={
                    "alpha": ProjectConfig(name="alpha", workdir=r"D:\\alpha"),
                },
            )
            scheduler = TaskScheduler(store, config)

            first = scheduler.enqueue("alpha", "task one")
            second = scheduler.enqueue("alpha", "task two")
            task_one = scheduler.get_task(first.task.task_id)
            task_two = scheduler.get_task(second.task.task_id)

            self.assertIsNotNone(task_one)
            self.assertIsNotNone(task_two)
            self.assertEqual(task_one.status, TaskStatus.RUNNING)
            self.assertEqual(task_two.status, TaskStatus.QUEUED)
            self.assertEqual([project.name for project in scheduler.list_projects()], ["alpha"])
            self.assertEqual(scheduler.create_task("alpha", "task three").status, TaskStatus.QUEUED)

            scheduler.complete(task_one.task_id, summary="done")

            refreshed_two = scheduler.get_task(task_two.task_id)
            self.assertEqual(refreshed_two.status, TaskStatus.RUNNING)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_confirmation_flow(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp = workspace_tmp / f"scheduler-{uuid.uuid4().hex}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = JsonStateStore(Path(tmp) / "state.json")
            config = ControllerConfig(
                state_file=store.path,
                projects={"alpha": ProjectConfig(name="alpha", workdir=r"D:\\alpha")},
            )
            scheduler = TaskScheduler(store, config)

            task = scheduler.enqueue("alpha", "task")
            scheduler.update_log(task.task.task_id, "running test command")
            self.assertEqual(scheduler.get_logs(task.task.task_id), "running test command")
            scheduler.update_summary(task.task.task_id, "summary text")
            self.assertEqual(scheduler.get_diff(task.task.task_id), "summary text")
            snapshot = scheduler.snapshot_task(task.task.task_id)
            self.assertEqual(snapshot["project"], "alpha")
            self.assertEqual(snapshot["logs"], "running test command")
            continued = scheduler.continue_task(task.task.task_id, "keep going")
            self.assertEqual(continued.status, TaskStatus.RUNNING)
            self.assertIn("keep going", continued.prompt)
            scheduler.request_confirmation(task.task.task_id, "git push")
            waiting = scheduler.get_task(task.task.task_id)
            self.assertEqual(waiting.status, TaskStatus.WAITING_CONFIRMATION)
            scheduler.confirm_task(task.task.task_id, approved=False)
            paused = scheduler.get_task(task.task.task_id)
            self.assertEqual(paused.status, TaskStatus.PAUSED)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
