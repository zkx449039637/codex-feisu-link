from __future__ import annotations

from dataclasses import dataclass, field
import shlex
from pathlib import Path
from typing import Any
import json
import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 not supported by project metadata
    tomllib = None  # type: ignore[assignment]

from .models import ProjectConfig


@dataclass(slots=True)
class ControllerConfig:
    state_file: Path
    projects: dict[str, ProjectConfig] = field(default_factory=dict)
    runtime_root: Path = field(default_factory=lambda: Path.cwd() / ".codex-feishu-link")
    runtime_state_file: Path | None = None
    runtime_log_dir: Path | None = None
    runtime_artifact_dir: Path | None = None
    codex_executable: str = "codex"
    codex_arguments: list[str] = field(default_factory=list)
    command_timeout_seconds: int = 600
    runtime_poll_interval_seconds: float = 2.0
    allowed_user_ids: set[str] = field(default_factory=set)
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_base_url: str = "https://open.feishu.cn"
    feishu_receive_id_type: str = "chat_id"


def _read_mapping_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".toml", ".tml"}:
        if tomllib is None:
            raise RuntimeError("tomllib is unavailable")
        return tomllib.loads(text)
    raise ValueError(f"Unsupported config file format: {path.suffix}")


def _parse_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value))


def _parse_string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [token for token in shlex.split(value) if token]
    return [str(value)]


def _parse_optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _parse_projects(raw: Any) -> dict[str, ProjectConfig]:
    projects: dict[str, ProjectConfig] = {}
    if isinstance(raw, dict):
        if all(isinstance(value, dict) for value in raw.values()):
            items = raw.items()
        else:
            items = []
    elif isinstance(raw, list):
        items = ((item["name"], item) for item in raw if isinstance(item, dict) and "name" in item)
    else:
        items = []
    for name, item in items:
        projects[str(name)] = ProjectConfig(
            name=str(item.get("name", name)),
            workdir=str(item["workdir"]),
            branch_prefix=str(item.get("branch_prefix", "codex/")),
            description=item.get("description"),
            max_parallel_tasks=int(item.get("max_parallel_tasks", 1)),
        )
    return projects


def load_controller_config(config_path: str | Path | None = None) -> ControllerConfig:
    explicit = Path(config_path) if config_path is not None else None
    env_path = os.getenv("CODEX_FEISHU_LINK_CONFIG")
    candidate = explicit or (Path(env_path) if env_path else None)
    data: dict[str, Any] = {}
    if candidate is not None:
        if candidate.exists():
            data = _read_mapping_file(candidate)
    state_file = Path(
        os.getenv(
            "CODEX_FEISHU_LINK_STATE_FILE",
            str(Path.cwd() / "state.json"),
        )
    )
    runtime_root = Path(
        os.getenv(
            "CODEX_FEISHU_LINK_RUNTIME_ROOT",
            str(Path.cwd() / ".codex-feishu-link"),
        )
    )
    runtime_state_file = _parse_path(os.getenv("CODEX_FEISHU_LINK_RUNTIME_STATE_FILE"))
    runtime_log_dir = _parse_path(os.getenv("CODEX_FEISHU_LINK_RUNTIME_LOG_DIR"))
    runtime_artifact_dir = _parse_path(os.getenv("CODEX_FEISHU_LINK_RUNTIME_ARTIFACT_DIR"))
    codex_executable = os.getenv("CODEX_FEISHU_LINK_CODEX_EXECUTABLE", "codex")
    codex_arguments = _parse_string_list(os.getenv("CODEX_FEISHU_LINK_CODEX_ARGUMENTS"))
    allowed_user_ids = {
        entry.strip()
        for entry in os.getenv("CODEX_FEISHU_LINK_ALLOWED_USER_IDS", "").split(",")
        if entry.strip()
    }
    feishu_app_id_env = _parse_optional_string(os.getenv("CODEX_FEISHU_LINK_FEISHU_APP_ID"))
    feishu_app_secret_env = _parse_optional_string(os.getenv("CODEX_FEISHU_LINK_FEISHU_APP_SECRET"))
    feishu_base_url_env = _parse_optional_string(os.getenv("CODEX_FEISHU_LINK_FEISHU_BASE_URL"))
    feishu_receive_id_type_env = _parse_optional_string(os.getenv("CODEX_FEISHU_LINK_FEISHU_RECEIVE_ID_TYPE"))
    feishu_app_id = feishu_app_id_env
    feishu_app_secret = feishu_app_secret_env
    feishu_base_url = feishu_base_url_env or "https://open.feishu.cn"
    feishu_receive_id_type = feishu_receive_id_type_env or "chat_id"
    projects = _parse_projects(data.get("projects", data.get("project", [])))
    command_timeout_seconds = int(
        data.get("command_timeout_seconds")
        or os.getenv("CODEX_FEISHU_LINK_COMMAND_TIMEOUT_SECONDS", "600")
    )
    runtime_poll_interval_seconds = float(
        data.get("runtime_poll_interval_seconds")
        or os.getenv("CODEX_FEISHU_LINK_RUNTIME_POLL_INTERVAL_SECONDS", "2.0")
    )
    if "state_file" in data:
        state_file = Path(str(data["state_file"]))
    if "runtime_root" in data:
        runtime_root = Path(str(data["runtime_root"]))
    if "runtime_state_file" in data:
        runtime_state_file = _parse_path(data["runtime_state_file"])
    if "runtime_log_dir" in data:
        runtime_log_dir = _parse_path(data["runtime_log_dir"])
    if "runtime_artifact_dir" in data:
        runtime_artifact_dir = _parse_path(data["runtime_artifact_dir"])
    if "codex_executable" in data:
        codex_executable = str(data["codex_executable"])
    if "codex_arguments" in data:
        codex_arguments = _parse_string_list(data["codex_arguments"])
    feishu_data = data.get("feishu") if isinstance(data.get("feishu"), dict) else {}
    if feishu_app_id is None and "feishu_app_id" in data:
        feishu_app_id = _parse_optional_string(data["feishu_app_id"])
    elif feishu_app_id is None and isinstance(feishu_data, dict) and "app_id" in feishu_data:
        feishu_app_id = _parse_optional_string(feishu_data["app_id"])
    if feishu_app_secret is None and "feishu_app_secret" in data:
        feishu_app_secret = _parse_optional_string(data["feishu_app_secret"])
    elif feishu_app_secret is None and isinstance(feishu_data, dict) and "app_secret" in feishu_data:
        feishu_app_secret = _parse_optional_string(feishu_data["app_secret"])
    if feishu_base_url_env is None and "feishu_base_url" in data:
        feishu_base_url = str(data["feishu_base_url"])
    elif feishu_base_url_env is None and isinstance(feishu_data, dict) and "base_url" in feishu_data:
        feishu_base_url = str(feishu_data["base_url"])
    if feishu_receive_id_type_env is None and "feishu_receive_id_type" in data:
        feishu_receive_id_type = str(data["feishu_receive_id_type"])
    elif feishu_receive_id_type_env is None and isinstance(feishu_data, dict) and "receive_id_type" in feishu_data:
        feishu_receive_id_type = str(feishu_data["receive_id_type"])
    return ControllerConfig(
        state_file=state_file,
        projects=projects,
        runtime_root=runtime_root,
        runtime_state_file=runtime_state_file,
        runtime_log_dir=runtime_log_dir,
        runtime_artifact_dir=runtime_artifact_dir,
        codex_executable=codex_executable,
        codex_arguments=codex_arguments,
        command_timeout_seconds=command_timeout_seconds,
        runtime_poll_interval_seconds=runtime_poll_interval_seconds,
        allowed_user_ids=allowed_user_ids,
        feishu_app_id=feishu_app_id,
        feishu_app_secret=feishu_app_secret,
        feishu_base_url=feishu_base_url.rstrip("/") or "https://open.feishu.cn",
        feishu_receive_id_type=feishu_receive_id_type,
    )
