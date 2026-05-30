from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from car.paths import ensure_dirs, state_file


@dataclass
class CarState:
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "openai/gpt-4o-mini"
    selected_model: str | None = None
    provider_lock: str | None = None
    provider_lock_mode: str = "strict"
    key_name: str = "openrouter_api_key"
    mattstash_cli: str = "mattstash"
    key_helper: str = ""


def _state_from_dict(data: dict[str, Any]) -> CarState:
    state = CarState()
    for key in state.__dataclass_fields__.keys():
        if key in data:
            setattr(state, key, data[key])
    return state


def load_state() -> CarState:
    ensure_dirs()
    file_path = state_file()
    if not file_path.exists():
        return _apply_env_overrides(CarState())

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _apply_env_overrides(CarState())

    return _apply_env_overrides(_state_from_dict(data))


def save_state(state: CarState) -> None:
    ensure_dirs()
    file_path = state_file()
    file_path.write_text(
        json.dumps(state.__dict__, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def selected_model(state: CarState) -> str:
    return state.selected_model or state.default_model


def resolve_openrouter_key(state: CarState) -> str | None:
    for key in (
        "CAR_OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY",
        "COPILOT_PROVIDER_API_KEY",
    ):
        value = os.environ.get(key, "").strip()
        if value:
            return value

    mattstash = state.mattstash_cli.strip()
    key_name = state.key_name.strip()
    if not mattstash or not key_name:
        return None

    try:
        result = subprocess.run(
            [mattstash, "get", key_name, "--show-password"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None

    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        return None

    return token


def _apply_env_overrides(state: CarState) -> CarState:
    base_url = os.environ.get("CAR_OPENROUTER_BASE_URL", "").strip()
    default_model = os.environ.get("CAR_DEFAULT_MODEL", "").strip()
    selected = os.environ.get("COPILOT_MODEL", "").strip()
    provider_lock = os.environ.get("CAR_PROVIDER_LOCK", "").strip()
    mode = os.environ.get("CAR_PROVIDER_LOCK_MODE", "").strip()

    if base_url:
        state.openrouter_base_url = base_url
    if default_model:
        state.default_model = default_model
    if selected:
        state.selected_model = selected
    if provider_lock:
        state.provider_lock = provider_lock
    if mode in {"strict", "prefer"}:
        state.provider_lock_mode = mode

    return state


def state_path() -> Path:
    return state_file()
