# codex-feishu-link

`codex-feishu-link` is a Windows-friendly bridge between Feishu and a local Codex CLI workflow.

It lets you control one or more local workspaces from Feishu messages, while keeping execution, logs, runtime state, and project routing on your own machine.

## What It Does

- Receives Feishu messages through long connection mode
- Parses a small, explicit command protocol
- Schedules local Codex tasks per project
- Keeps per-project single-writer execution semantics
- Stores task state, runtime state, logs, and artifacts on disk
- Supports foreground debugging and background service mode on Windows

## Core Commands

- `projects`
- `tasks [project]`
- `new <project> <description...>`
- `status <task_id>`
- `logs <task_id>`
- `diff <task_id>`
- `continue <task_id> [instruction...]`
- `pause <task_id>`
- `resume <task_id>`
- `stop <task_id>`
- `confirm <task_id> yes|no`
- `snapshot <task_id>`

## Repository Layout

- `src/codex_feishu_link/models.py`: task, project, execution, and runtime models
- `src/codex_feishu_link/storage.py`: JSON-backed state persistence
- `src/codex_feishu_link/scheduler.py`: queueing, admission, confirmation, and task transitions
- `src/codex_feishu_link/commands.py`: Feishu command parser
- `src/codex_feishu_link/bootstrap.py`: local and service bootstrap entrypoints
- `run-service.ps1`: foreground launcher
- `start-background.ps1`: hidden background launcher
- `service-status.ps1`: background service status
- `stop-background.ps1`: stop the tracked background service
- `stop-all.ps1`: stop every local `codex_feishu_link` process on this machine

## Quick Start

1. Create a virtual environment.
2. Install the package and Feishu SDK.
3. Generate `config.local.json`.
4. Fill in machine-specific values.
5. Start the background service.
6. Send `projects` in Feishu to verify the bot is online.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . lark-oapi
.\init-machine.ps1 -Force -MachineName $env:COMPUTERNAME -ProjectName "codex-feishu-link" -ProjectPath "$PWD"
.\start-background.ps1
```

The PowerShell launcher still supports the direct module path and explicit modes:

```powershell
.\run-service.ps1 -Mode local
.\run-service.ps1 -Mode service
python -m codex_feishu_link --mode local
python -m codex_feishu_link --mode service --config ".\config.local.json"
```

If you want to point the launcher at another config file, set `CODEX_FEISHU_LINK_CONFIG`.

## Required Config Values

Before service mode can do real work, you need:

- `feishu.app_id`
- `feishu.app_secret`
- `feishu.allowed_user_ids`
- at least one project `workdir`

The real local config should live in `config.local.json`. Do not commit that file.

## Windows Operation

Daily-use commands:

```powershell
.\start-background.ps1
.\service-status.ps1
.\stop-background.ps1
.\stop-all.ps1
```

Foreground debugging:

```powershell
.\run-service.ps1 -Mode service
```

Double-click startup:

- `start-background.cmd`

## Auto Start On Login

This repo includes a scheduled-task based auto-start setup for Windows login sessions.

Register auto-start:

```powershell
.\register-autostart.ps1
```

Check task status:

```powershell
.\autostart-status.ps1
```

Remove auto-start:

```powershell
.\unregister-autostart.ps1
```

By default, the task launches `start-background.ps1` at user logon.

## Documentation

- [Chinese usage guide](./使用说明.md)
- [Deployment guide](./DEPLOYMENT.md)

## Example Config

`config.example.json` shows the expected structure:

```json
{
  "state_file": "D:\\Codex Projects\\codex-feisu-link\\.state\\state.json",
  "runtime_root": "D:\\Codex Projects\\codex-feisu-link\\.runtime",
  "runtime_state_file": "D:\\Codex Projects\\codex-feisu-link\\.runtime\\runtime-state.json",
  "runtime_log_dir": "D:\\Codex Projects\\codex-feisu-link\\.runtime\\logs",
  "runtime_artifact_dir": "D:\\Codex Projects\\codex-feisu-link\\.runtime\\artifacts",
  "codex_executable": "codex",
  "codex_arguments": [],
  "command_timeout_seconds": 600,
  "runtime_poll_interval_seconds": 2.0,
  "feishu": {
    "app_id": "cli_replace_me",
    "app_secret": "replace_me",
    "base_url": "https://open.feishu.cn",
    "receive_id_type": "chat_id",
    "allowed_user_ids": ["ou_replace_me"]
  },
  "projects": {
    "codex-feishu-link": {
      "name": "codex-feishu-link",
      "workdir": "D:\\Codex Projects\\codex-feisu-link",
      "branch_prefix": "codex/",
      "description": "Local Feishu-controlled Codex orchestration workspace.",
      "max_parallel_tasks": 1
    }
  }
}
```

## Testing

Run the test suite with:

```powershell
python -m unittest discover -s tests -v
```
