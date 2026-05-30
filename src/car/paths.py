from __future__ import annotations

from pathlib import Path


APP_NAME = "car"


def xdg_config_home() -> Path:
    return Path.home().joinpath(".config")


def xdg_cache_home() -> Path:
    return Path.home().joinpath(".cache")


def app_config_dir() -> Path:
    return xdg_config_home().joinpath(APP_NAME)


def app_cache_dir() -> Path:
    return xdg_cache_home().joinpath(APP_NAME)


def state_file() -> Path:
    return app_config_dir().joinpath("state.json")


def models_cache_file() -> Path:
    return app_cache_dir().joinpath("models.json")


def ensure_dirs() -> None:
    app_config_dir().mkdir(parents=True, exist_ok=True)
    app_cache_dir().mkdir(parents=True, exist_ok=True)
