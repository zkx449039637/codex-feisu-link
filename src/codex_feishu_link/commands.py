"""Command parsing for the Feishu-controlled Codex CLI orchestrator.

The protocol is intentionally small and explicit so that the chat surface can
drive multiple concurrent tasks without ambiguity:

- projects
- tasks [project]
- new <project> <description...>
- status <task_id>
- logs <task_id>
- diff <task_id>
- continue <task_id> [instruction...]
- pause <task_id>
- resume <task_id>
- stop <task_id>
- confirm <task_id> yes|no
- snapshot <task_id>
"""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Iterable


class CommandParseError(ValueError):
    """Raised when an incoming text command cannot be parsed."""


@dataclass(frozen=True, slots=True)
class Command:
    """Structured representation of a supported chat command."""

    name: str
    project: str | None = None
    task_id: str | None = None
    text: str = ""
    decision: bool | None = None
    raw: str = ""

    def with_text(self, text: str) -> "Command":
        return Command(
            name=self.name,
            project=self.project,
            task_id=self.task_id,
            text=text,
            decision=self.decision,
            raw=self.raw,
        )


_NO_ARGUMENT_COMMANDS = {"projects"}
_ONE_TASK_COMMANDS = {"status", "logs", "diff", "pause", "resume", "stop", "snapshot"}


def _strip_bot_mention(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("@"):
        return stripped

    parts = stripped.split(maxsplit=1)
    if len(parts) == 1:
        return ""
    return parts[1].strip()


def _tokenize(text: str) -> list[str]:
    if not text.strip():
        raise CommandParseError("empty command")
    return shlex.split(text, posix=True)


def _join_rest(tokens: Iterable[str]) -> str:
    return " ".join(token for token in tokens if token)


def parse_command(text: str) -> Command:
    """Parse a plain text message into a structured command.

    The parser is strict enough to prevent accidental cross-task actions, but
    tolerant of leading bot mentions and quoted text.
    """

    normalized = _strip_bot_mention(text)
    tokens = _tokenize(normalized)
    name = tokens[0].lower()
    raw = text.strip()

    if name in _NO_ARGUMENT_COMMANDS:
        if len(tokens) != 1:
            raise CommandParseError(f"`{name}` does not accept arguments")
        return Command(name=name, raw=raw)

    if name == "tasks":
        if len(tokens) > 2:
            raise CommandParseError("`tasks` accepts at most one project argument")
        project = tokens[1] if len(tokens) == 2 else None
        return Command(name=name, project=project, raw=raw)

    if name == "new":
        if len(tokens) < 3:
            raise CommandParseError("`new` requires a project and a description")
        return Command(name=name, project=tokens[1], text=_join_rest(tokens[2:]), raw=raw)

    if name in _ONE_TASK_COMMANDS:
        if len(tokens) != 2:
            raise CommandParseError(f"`{name}` requires exactly one task id")
        return Command(name=name, task_id=tokens[1], raw=raw)

    if name == "continue":
        if len(tokens) < 2:
            raise CommandParseError("`continue` requires a task id")
        return Command(name=name, task_id=tokens[1], text=_join_rest(tokens[2:]), raw=raw)

    if name == "confirm":
        if len(tokens) != 3:
            raise CommandParseError("`confirm` requires a task id and `yes` or `no`")
        decision_token = tokens[2].lower()
        if decision_token not in {"yes", "no"}:
            raise CommandParseError("`confirm` decision must be `yes` or `no`")
        return Command(
            name=name,
            task_id=tokens[1],
            decision=decision_token == "yes",
            raw=raw,
        )

    raise CommandParseError(f"unsupported command: {tokens[0]}")


def command_help() -> str:
    return (
        "Supported commands: projects, tasks [project], new <project> <description>, "
        "status <task_id>, logs <task_id>, diff <task_id>, continue <task_id> "
        "[instruction], pause <task_id>, resume <task_id>, stop <task_id>, "
        "confirm <task_id> yes|no, snapshot <task_id>"
    )
