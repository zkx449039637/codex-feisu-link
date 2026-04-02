# Deployment Guide

This repo is designed to be copied onto another Windows machine and brought online with the same workflow.

## What Is Reusable

- The repo itself, including `src/`, `tests/`, `run-service.ps1`, and `config.example.json`
- The command protocol
- The Feishu long-connection service implementation
- The local Codex runtime and task scheduler
- Any project list you want to manage on that machine

## What Is Machine-Specific

- `config.local.json`
- `feishu.app_id`
- `feishu.app_secret`
- `feishu.allowed_user_ids`
- Each project `workdir`
- `codex_executable` and `codex_arguments` if that machine uses a different Codex install path
- `runtime_root`, `runtime_state_file`, `runtime_log_dir`, and `runtime_artifact_dir` if you want machine-specific storage

## Reuse The Same Feishu Bot Or Create A New One

You can reuse the same Feishu bot if only one machine should be active at a time.

- Stop the old machine's service before starting the new one
- Start the service on the new machine with the same bot credentials

Create a new Feishu bot if you want multiple machines online at the same time.

- One bot per machine
- Give each bot its own `app_id` and `app_secret`
- Keep each machine's `allowed_user_ids` narrow to the people who should control that machine

## Second Machine Quick Start

1. Copy this repository to the second Windows machine.
2. Open PowerShell in the repo root.
3. Create and activate a virtual environment.

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

4. Install the Python package in editable mode.

```powershell
pip install -e .
```

5. Install the Feishu SDK.

```powershell
pip install lark-oapi
```

6. Prepare a local config.

```powershell
Copy-Item .\config.example.json .\config.local.json
```

7. Edit `config.local.json` and set the machine-specific values listed above.
8. Make sure the machine can run Codex.
9. Start the service and keep the window open.

```powershell
python -m codex_feishu_link --mode service --config "D:\Codex project\codex-feisu-link\config.local.json"
```

10. Send `projects` in Feishu to confirm the bot is online.

If you want the service to stay up without keeping a terminal open, use the background launcher instead:

```powershell
.\start-background.ps1
```

Useful companion commands:

- `.\service-status.ps1`
- `.\stop-background.ps1`
- double-click `start-background.cmd`

## Minimal Values To Fill

If you only want the bare minimum for a second machine, fill these values first:

- `feishu.app_id`
- `feishu.app_secret`
- `feishu.allowed_user_ids`
- one project `workdir`
- `codex_executable`

## If You Want The Fastest Repeatable Setup

Use the same structure every time:

- clone or copy the repo
- create `.venv`
- install `lark-oapi`
- copy `config.example.json` to `config.local.json`
- fill only machine-specific values
- start `service` mode and keep it running
