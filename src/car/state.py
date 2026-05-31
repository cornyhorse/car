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
    route_mode: str = "model"
    favorite_models: list[str] | None = None
    key_name: str = "openrouter_api_key"
    mattstash_cli: str = "mattstash"
    key_helper: str = ""

    def __post_init__(self) -> None:
        if self.favorite_models is None:
            self.favorite_models = []


def _state_from_dict(data: dict[str, Any]) -> CarState:
    state = CarState()
    for key in state.__dataclass_fields__.keys():
        if key in data:
            setattr(state, key, data[key])

    if not isinstance(state.favorite_models, list):
        state.favorite_models = []
    else:
        state.favorite_models = [str(x) for x in state.favorite_models if str(x).strip()]

    if state.route_mode not in {"model", "provider"}:
        state.route_mode = "model"

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
    token, _source = resolve_openrouter_key_with_source(state)
    return token


def resolve_openrouter_key_with_source(
    state: CarState,
) -> tuple[str | None, str | None]:
    source_hint = os.environ.get("CAR_OPENROUTER_KEY_SOURCE", "").strip()

    for key in (
        "CAR_OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY",
        "COPILOT_PROVIDER_API_KEY",
    ):
        value = os.environ.get(key, "").strip()
        if value:
            if key == "COPILOT_PROVIDER_API_KEY" and source_hint.startswith("mattstash:"):
                return value, source_hint
            return value, key

    mattstash = state.mattstash_cli.strip()
    key_name = state.key_name.strip()
    if not mattstash or not key_name:
        return None, None

    token = _mattstash_get_value(mattstash, key_name)
    if not token:
        return None, None

    return token, f"mattstash:{key_name}"


def store_openrouter_key(
    state: CarState,
    value: str,
    key_name: str | None = None,
) -> str:
    mattstash = state.mattstash_cli.strip()
    resolved_key_name = (key_name if key_name is not None else state.key_name).strip()
    token = value.strip()

    if not mattstash:
        raise RuntimeError("mattstash CLI is not configured")
    if not resolved_key_name:
        raise RuntimeError("key name is not configured")
    if not token:
        raise RuntimeError("OpenRouter API key is empty")

    try:
        result = subprocess.run(
            [mattstash, "put", resolved_key_name, "--value", token],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("mattstash executable not found") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or "unable to store key"
        raise RuntimeError(f"mattstash put failed: {detail}")

    read_back = _mattstash_get_value(mattstash, resolved_key_name)
    if not read_back:
        raise RuntimeError("stored key could not be read back from mattstash")

    if read_back != token:
        raise RuntimeError(
            "mattstash stored value does not match input; check mattstash configuration/version"
        )

    return resolved_key_name


def _apply_env_overrides(state: CarState) -> CarState:
    base_url = os.environ.get("CAR_OPENROUTER_BASE_URL", "").strip()
    default_model = os.environ.get("CAR_DEFAULT_MODEL", "").strip()
    selected = os.environ.get("COPILOT_MODEL", "").strip()
    provider_lock = os.environ.get("CAR_PROVIDER_LOCK", "").strip()
    mode = os.environ.get("CAR_PROVIDER_LOCK_MODE", "").strip()
    route_mode = os.environ.get("CAR_ROUTE_MODE", "").strip()
    mattstash_cli = os.environ.get("CAR_MATTSTASH_CLI", "").strip()
    key_name = os.environ.get("CAR_MATTSTASH_KEY_NAME", "").strip()

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
    if route_mode in {"model", "provider"}:
        state.route_mode = route_mode
    if mattstash_cli:
        state.mattstash_cli = mattstash_cli
    if key_name:
        state.key_name = key_name

    return state


def state_path() -> Path:
    return state_file()


def _mattstash_get_value(mattstash: str, key_name: str) -> str | None:
    for cmd in (
        [mattstash, "get", key_name, "--show-password", "--json"],
        [mattstash, "get", key_name, "--show-password"],
    ):
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return None

        if result.returncode != 0:
            continue

        token = _extract_mattstash_value(result.stdout)
        if token:
            return token

    return None


def _extract_mattstash_value(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None

    has_json = False
    try:
        parsed = json.loads(raw)
        has_json = True
    except json.JSONDecodeError:
        parsed = None

    if has_json:
        if isinstance(parsed, dict):
            value = parsed.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("value:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                return value

    if "\n" not in text:
        return text

    return None
