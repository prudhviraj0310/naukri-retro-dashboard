from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config/candidate_profile.json")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_workspace_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None

    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path
