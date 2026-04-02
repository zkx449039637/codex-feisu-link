from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from .models import TaskRecord


@dataclass(slots=True)
class StateSnapshot:
    version: int = 1
    tasks: dict[str, TaskRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tasks": {task_id: task.to_dict() for task_id, task in self.tasks.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateSnapshot":
        tasks = {
            task_id: TaskRecord.from_dict(task_data)
            for task_id, task_data in dict(data.get("tasks", {})).items()
        }
        return cls(version=int(data.get("version", 1)), tasks=tasks)


class JsonStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> StateSnapshot:
        if not self.path.exists():
            return StateSnapshot()
        return StateSnapshot.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, snapshot: StateSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self.path)

    def update(self, mutator) -> StateSnapshot:
        snapshot = self.load()
        result = mutator(snapshot)
        if isinstance(result, StateSnapshot):
            snapshot = result
        self.save(snapshot)
        return snapshot
