from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.config import ControllerConfig, ProjectConfig  # noqa: E402
from codex_feishu_link.executor import ExecutionHandle, SubprocessCodexExecutor  # noqa: E402
from codex_feishu_link.models import ExecutionRequest, RuntimeStatus, TaskStatus, utc_now  # noqa: E402
from codex_feishu_link.runtime import JsonRuntimeStateStore, LocalCodexRuntime  # noqa: E402
from codex_feishu_link.scheduler import TaskScheduler  # noqa: E402
from codex_feishu_link.storage import JsonStateStore  # noqa: E402


class FakeProcess:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = 130

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class RecordingSpawner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.process = FakeProcess()

    def __call__(self, command: list[str], **kwargs):
        self.calls.append({"command": list(command), "kwargs": kwargs})
        stdout = kwargs["stdout"]
        stdout.write("fake process output\n")
        stdout.flush()
        return self.process


class FakeExecutor:
    def __init__(self) -> None:
        self.started: dict[str, ExecutionHandle] = {}
        self.finalized: list[dict[str, object]] = []
        self.processes: dict[str, FakeProcess] = {}

    def start(self, request: ExecutionRequest) -> ExecutionHandle:
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        request.log_file.parent.mkdir(parents=True, exist_ok=True)
        request.log_file.write_text("executor started\n", encoding="utf-8")
        process = FakeProcess(pid=5000 + len(self.processes))
        self.processes[request.task_id] = process
        handle = ExecutionHandle(
            request=request,
            process=process,
            started_at=utc_now(),
            log_file=request.log_file,
            artifact_dir=request.artifact_dir,
        )
        self.started[request.task_id] = handle
        return handle

    def stop(self, handle: ExecutionHandle, *, force: bool = False, wait_seconds: float = 5.0) -> None:
        handle.terminate()
        if force:
            handle.kill()

    def finalize(
        self,
        handle: ExecutionHandle,
        *,
        returncode: int,
        finished_at=None,
        summary: str = "",
        error: str | None = None,
        canceled: bool = False,
    ):
        from codex_feishu_link.executor import SubprocessCodexExecutor

        result = SubprocessCodexExecutor().finalize(
            handle,
            returncode=returncode,
            finished_at=finished_at,
            summary=summary,
            error=error,
            canceled=canceled,
        )
        self.finalized.append(result.to_dict())
        return result


class ExecutorTests(unittest.TestCase):
    def test_subprocess_executor_uses_injected_spawner(self) -> None:
        root = Path(__file__).resolve().parents[1] / ".test_tmp" / f"executor_{os.getpid()}_{uuid4().hex}"
        try:
            root.mkdir(parents=True, exist_ok=True)
            spawner = RecordingSpawner()
            executor = SubprocessCodexExecutor(spawner=spawner)
            request = ExecutionRequest(
                task_id="task-1",
                project="alpha",
                command=["codex", "--version"],
                workdir=root,
                prompt="fix login flow",
                prompt_file=root / "artifacts" / "task-1" / "prompt.txt",
                log_file=root / "logs" / "task-1.log",
                artifact_dir=root / "artifacts" / "task-1",
                env={"EXTRA": "1"},
            )

            handle = executor.start(request)

            self.assertEqual(handle.pid, spawner.process.pid)
            self.assertTrue(request.prompt_file.exists())
            self.assertTrue(request.log_file.exists())
            self.assertTrue((request.artifact_dir / "request.json").exists())
            self.assertEqual(spawner.calls[0]["command"], ["codex", "--version"])
            kwargs = spawner.calls[0]["kwargs"]
            self.assertEqual(kwargs["cwd"], str(root))
            self.assertEqual(kwargs["env"]["EXTRA"], "1")
            self.assertEqual(kwargs["env"]["CODEX_FEISHU_LINK_TASK_ID"], "task-1")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_runtime_launches_and_finishes_task(self) -> None:
        root = Path(__file__).resolve().parents[1] / ".test_tmp" / f"runtime_{os.getpid()}_{uuid4().hex}"
        try:
            root.mkdir(parents=True, exist_ok=True)
            store = JsonStateStore(root / "scheduler-state.json")
            runtime_store = JsonRuntimeStateStore(root / "runtime-state.json")
            config = ControllerConfig(
                state_file=store.path,
                projects={"alpha": ProjectConfig(name="alpha", workdir=str(root / "work" / "alpha"))},
                runtime_root=root / "runtime",
                runtime_state_file=root / "runtime" / "runtime-state.json",
                runtime_log_dir=root / "runtime" / "logs",
                runtime_artifact_dir=root / "runtime" / "artifacts",
                codex_executable="codex",
                codex_arguments=["--non-interactive"],
            )
            scheduler = TaskScheduler(store, config)
            task = scheduler.enqueue("alpha", "build login flow").task
            fake_executor = FakeExecutor()
            runtime = LocalCodexRuntime(
                scheduler,
                config,
                executor=fake_executor,
                state_store=runtime_store,
            )

            first_results = runtime.step()
            self.assertEqual(first_results, [])
            self.assertIn(task.task_id, fake_executor.started)
            self.assertTrue((config.runtime_artifact_dir / "alpha" / task.task_id / "request.json").exists())
            self.assertEqual(scheduler.get_task(task.task_id).status, TaskStatus.RUNNING)

            process = fake_executor.processes[task.task_id]
            process.returncode = 0
            log_file = config.runtime_log_dir / "alpha" / f"{task.task_id}.log"
            log_file.write_text("executor started\nfinished successfully\n", encoding="utf-8")

            second_results = runtime.step()

            self.assertEqual(len(second_results), 1)
            self.assertEqual(second_results[0].task_id, task.task_id)
            self.assertEqual(second_results[0].returncode, 0)
            self.assertEqual(scheduler.get_task(task.task_id).status, TaskStatus.COMPLETED)
            runtime_state = runtime_store.load()
            self.assertEqual(runtime_state.tasks[task.task_id].status, RuntimeStatus.COMPLETED)
            self.assertTrue((config.runtime_artifact_dir / "alpha" / task.task_id / "result.json").exists())
            self.assertIn("finished successfully", scheduler.get_task(task.task_id).latest_log)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_runtime_stops_when_task_is_paused(self) -> None:
        root = Path(__file__).resolve().parents[1] / ".test_tmp" / f"pause_{os.getpid()}_{uuid4().hex}"
        try:
            root.mkdir(parents=True, exist_ok=True)
            store = JsonStateStore(root / "scheduler-state.json")
            runtime_store = JsonRuntimeStateStore(root / "runtime-state.json")
            config = ControllerConfig(
                state_file=store.path,
                projects={"alpha": ProjectConfig(name="alpha", workdir=str(root / "work" / "alpha"))},
                runtime_root=root / "runtime",
                runtime_state_file=root / "runtime" / "runtime-state.json",
                runtime_log_dir=root / "runtime" / "logs",
                runtime_artifact_dir=root / "runtime" / "artifacts",
            )
            scheduler = TaskScheduler(store, config)
            task = scheduler.enqueue("alpha", "build login flow").task
            fake_executor = FakeExecutor()
            runtime = LocalCodexRuntime(
                scheduler,
                config,
                executor=fake_executor,
                state_store=runtime_store,
            )

            runtime.step()
            scheduler.pause(task.task_id)
            runtime.step()

            process = fake_executor.processes[task.task_id]
            self.assertTrue(process.terminated)
            self.assertEqual(runtime_store.load().tasks[task.task_id].status, RuntimeStatus.PAUSED)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
