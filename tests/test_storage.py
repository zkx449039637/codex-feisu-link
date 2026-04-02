from __future__ import annotations

from pathlib import Path
import sys
import unittest
import shutil
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.models import TaskRecord, TaskStatus
from codex_feishu_link.storage import JsonStateStore, StateSnapshot


class StorageTests(unittest.TestCase):
    def test_round_trip_snapshot(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp = workspace_tmp / f"storage-{uuid.uuid4().hex}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            path = tmp / "state.json"
            store = JsonStateStore(path)
            snapshot = StateSnapshot(
                tasks={
                    "task_1": TaskRecord.create("demo", "hello", task_id="task_1"),
                }
            )
            snapshot.tasks["task_1"].transition(TaskStatus.RUNNING)
            store.save(snapshot)

            loaded = store.load()

            self.assertIn("task_1", loaded.tasks)
            self.assertEqual(loaded.tasks["task_1"].status, TaskStatus.RUNNING)
            self.assertEqual(loaded.tasks["task_1"].project, "demo")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
