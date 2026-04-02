# codex-feishu-link

`codex-feishu-link` is a Windows-friendly control plane for running a local Codex CLI workflow from Feishu.

The project is split into layers:

- a core runtime that tracks projects, tasks, state, and single-writer scheduling per project
- a public app layer that parses Feishu-style commands and routes them to a scheduler backend
- a transport/runtime layer that can connect Feishu long-connection events and a local Codex executor
- a bootstrap layer that composes the pieces into either a local REPL or a service process

## Current Layout

- `src/codex_feishu_link/models.py` defines the task, project, request, result, and runtime state models.
- `src/codex_feishu_link/storage.py` persists task state as JSON on disk.
- `src/codex_feishu_link/scheduler.py` manages queueing, task transitions, confirmations, and per-project single-writer admission.
- `src/codex_feishu_link/commands.py` parses the supported chat command protocol.
- `src/codex_feishu_link/feishu_adapter.py` normalizes Feishu payloads without making network calls.
- `src/codex_feishu_link/bootstrap.py` builds the runtime and runs either the local REPL or a service loop.
- `run-service.ps1` is the Windows launcher that chooses local or service mode from config and environment.
- `config.example.json` is the starter configuration file for a Windows user.

## Supported Commands

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

## Windows Quick Start

1. Open `config.example.json` and fill in the placeholder values.
2. Save your real config as `config.local.json` in the repo root, or point `CODEX_FEISHU_LINK_CONFIG` to a different file.
3. Run the launcher:

```powershell
.\run-service.ps1
```

4. Use `-Mode local` for the REPL smoke test, or run the module directly with:

```powershell
python -m codex_feishu_link --mode local
```

5. Use `-Mode service` once your Feishu credentials and runtime settings are ready.

## Windows Background Service

For daily use on one machine, keep the foreground launcher for debugging and use the background launcher for normal operation.

- Foreground debug run: `.\run-service.ps1 -Mode service`
- Background run: `.\start-background.ps1`
- Double-click run: `start-background.cmd`
- Check background status: `.\service-status.ps1`
- Stop background service: `.\stop-background.ps1`

The background launcher starts a hidden PowerShell process, writes its PID to `.runtime\service\service.pid`, and stores logs in:

- `.runtime\service\service.stdout.log`
- `.runtime\service\service.stderr.log`

For a repeatable multi-machine rollout, see [DEPLOYMENT.md](./DEPLOYMENT.md).

## Required Values

These are the values you still need to provide before the service can do real work:

- `feishu.app_id`
- `feishu.app_secret`
- `feishu.allowed_user_ids`
- at least one project `workdir`
- the `codex_executable` that matches your local Codex CLI installation

Optional but useful values:

- `feishu.base_url`
- `feishu.receive_id_type`
- `codex_arguments`
- `runtime_root`
- `runtime_state_file`
- `runtime_log_dir`
- `runtime_artifact_dir`
- `runtime_poll_interval_seconds`

## Environment Variables

- `CODEX_FEISHU_LINK_CONFIG`
- `CODEX_FEISHU_LINK_STATE_FILE`
- `CODEX_FEISHU_LINK_RUNTIME_ROOT`
- `CODEX_FEISHU_LINK_RUNTIME_STATE_FILE`
- `CODEX_FEISHU_LINK_RUNTIME_LOG_DIR`
- `CODEX_FEISHU_LINK_RUNTIME_ARTIFACT_DIR`
- `CODEX_FEISHU_LINK_CODEX_EXECUTABLE`
- `CODEX_FEISHU_LINK_CODEX_ARGUMENTS`
- `CODEX_FEISHU_LINK_ALLOWED_USER_IDS`
- `CODEX_FEISHU_LINK_COMMAND_TIMEOUT_SECONDS`
- `CODEX_FEISHU_LINK_RUNTIME_POLL_INTERVAL_SECONDS`
- `CODEX_FEISHU_LINK_PYTHON`

## Example Config

The example config already includes the directories and object shapes the runtime expects. Update the placeholders before using service mode, or copy it to `config.local.json` and customize that file per machine.

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

The README example tests verify the sample config, the documented launcher commands, and the deployment guide link, while the bootstrap and integration tests cover the local REPL path and the service wiring contract.
