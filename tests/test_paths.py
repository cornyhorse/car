from __future__ import annotations

from pathlib import Path

from car import paths


def test_path_helpers_use_home(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)

    assert paths.xdg_config_home() == tmp_path / ".config"
    assert paths.xdg_cache_home() == tmp_path / ".cache"
    assert paths.app_config_dir() == tmp_path / ".config" / "car"
    assert paths.app_cache_dir() == tmp_path / ".cache" / "car"
    assert paths.state_file() == tmp_path / ".config" / "car" / "state.json"
    assert paths.models_cache_file() == tmp_path / ".cache" / "car" / "models.json"


def test_ensure_dirs_creates_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)

    paths.ensure_dirs()

    assert (tmp_path / ".config" / "car").is_dir()
    assert (tmp_path / ".cache" / "car").is_dir()
