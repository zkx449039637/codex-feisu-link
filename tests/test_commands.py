from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_feishu_link.commands import CommandParseError, parse_command  # noqa: E402


class CommandParsingTests(unittest.TestCase):
    def test_projects(self) -> None:
        command = parse_command("projects")
        self.assertEqual(command.name, "projects")

    def test_tasks_with_project(self) -> None:
        command = parse_command("tasks admin-web")
        self.assertEqual(command.name, "tasks")
        self.assertEqual(command.project, "admin-web")

    def test_new_with_quoted_description(self) -> None:
        command = parse_command('new admin-web "fix login flow" and tests')
        self.assertEqual(command.name, "new")
        self.assertEqual(command.project, "admin-web")
        self.assertEqual(command.text, "fix login flow and tests")

    def test_status(self) -> None:
        command = parse_command("status T1024")
        self.assertEqual(command.name, "status")
        self.assertEqual(command.task_id, "T1024")

    def test_continue_with_instruction(self) -> None:
        command = parse_command("continue T1024 do not touch UI")
        self.assertEqual(command.name, "continue")
        self.assertEqual(command.task_id, "T1024")
        self.assertEqual(command.text, "do not touch UI")

    def test_confirm_yes(self) -> None:
        command = parse_command("confirm T1024 yes")
        self.assertEqual(command.name, "confirm")
        self.assertTrue(command.decision)

    def test_confirm_no(self) -> None:
        command = parse_command("confirm T1024 no")
        self.assertFalse(command.decision)

    def test_mention_prefix_is_ignored(self) -> None:
        command = parse_command("@codex pause T1024")
        self.assertEqual(command.name, "pause")
        self.assertEqual(command.task_id, "T1024")

    def test_invalid_command(self) -> None:
        with self.assertRaises(CommandParseError):
            parse_command("unknown foo")

    def test_missing_args_are_rejected(self) -> None:
        with self.assertRaises(CommandParseError):
            parse_command("new admin-web")


if __name__ == "__main__":
    unittest.main()
