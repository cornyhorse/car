from __future__ import annotations

import json
import subprocess

import pytest

from car import state


def test_load_state_defaults_when_missing(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)

    result = state.load_state()

    assert result.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert result.default_model == "openai/gpt-4o-mini"
    assert result.provider_lock_mode == "strict"
    assert result.route_mode == "model"
    assert result.favorite_models == []


def test_load_state_from_file_and_env_override(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    f.write_text(
        json.dumps({
            "default_model": "x/y",
            "selected_model": "a/b",
            "provider_lock_mode": "strict",
            "route_mode": "provider",
            "favorite_models": ["a/b"],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    monkeypatch.setenv("CAR_DEFAULT_MODEL", "override/model")
    monkeypatch.setenv("COPILOT_MODEL", "selected/by/env")
    monkeypatch.setenv("CAR_PROVIDER_LOCK", "aws-bedrock")
    monkeypatch.setenv("CAR_PROVIDER_LOCK_MODE", "prefer")
    monkeypatch.setenv("CAR_ROUTE_MODE", "model")

    result = state.load_state()

    assert result.default_model == "override/model"
    assert result.selected_model == "selected/by/env"
    assert result.provider_lock == "aws-bedrock"
    assert result.provider_lock_mode == "prefer"
    assert result.route_mode == "model"
    assert result.favorite_models == ["a/b"]


def test_load_state_ignores_invalid_lock_mode(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    monkeypatch.setenv("CAR_PROVIDER_LOCK_MODE", "invalid")

    result = state.load_state()

    assert result.provider_lock_mode == "strict"


def test_load_state_ignores_invalid_route_mode(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    monkeypatch.setenv("CAR_ROUTE_MODE", "invalid")

    result = state.load_state()

    assert result.route_mode == "model"


def test_load_state_applies_base_url_override(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    monkeypatch.setenv("CAR_OPENROUTER_BASE_URL", "https://example.test/v1")

    result = state.load_state()

    assert result.openrouter_base_url == "https://example.test/v1"


def test_load_state_applies_mattstash_overrides(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    monkeypatch.setenv("CAR_MATTSTASH_CLI", "/usr/local/bin/mattstash")
    monkeypatch.setenv("CAR_MATTSTASH_KEY_NAME", "openrouter.apikey")

    result = state.load_state()

    assert result.mattstash_cli == "/usr/local/bin/mattstash"
    assert result.key_name == "openrouter.apikey"


def test_load_state_invalid_json_falls_back(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    f.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)

    result = state.load_state()

    assert isinstance(result, state.CarState)


def test_save_state_writes_json(monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    monkeypatch.setattr(state, "state_file", lambda: f)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)

    payload = state.CarState(selected_model="abc", favorite_models=["abc"])
    state.save_state(payload)

    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["selected_model"] == "abc"
    assert data["favorite_models"] == ["abc"]


def test_selected_model_prefers_selected_then_default():
    s1 = state.CarState(default_model="def", selected_model="sel")
    s2 = state.CarState(default_model="def", selected_model=None)

    assert state.selected_model(s1) == "sel"
    assert state.selected_model(s2) == "def"


def test_resolve_openrouter_key_from_env_precedence(monkeypatch):
    monkeypatch.setenv("CAR_OPENROUTER_API_KEY", "a")
    monkeypatch.setenv("OPENROUTER_API_KEY", "b")
    monkeypatch.setenv("COPILOT_PROVIDER_API_KEY", "c")

    result = state.resolve_openrouter_key(state.CarState())

    assert result == "a"

    token, source = state.resolve_openrouter_key_with_source(state.CarState())
    assert token == "a"
    assert source == "CAR_OPENROUTER_API_KEY"


def test_resolve_openrouter_key_from_mattstash(monkeypatch):
    monkeypatch.delenv("CAR_OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_PROVIDER_API_KEY", raising=False)

    completed = subprocess.CompletedProcess(
        args=["mattstash"], returncode=0, stdout="token\n", stderr=""
    )
    monkeypatch.setattr(state.subprocess, "run", lambda *a, **k: completed)

    result = state.resolve_openrouter_key(state.CarState())

    assert result == "token"

    token, source = state.resolve_openrouter_key_with_source(state.CarState())
    assert token == "token"
    assert source == "mattstash:openrouter_api_key"


def test_resolve_openrouter_key_with_source_uses_env_key_name_override(monkeypatch):
    monkeypatch.delenv("CAR_OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_PROVIDER_API_KEY", raising=False)
    monkeypatch.setenv("CAR_MATTSTASH_KEY_NAME", "openrouter.apikey")

    seen = {"cmd": None}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="token\n",
            stderr="",
        )

    monkeypatch.setattr(state.subprocess, "run", fake_run)

    loaded = state.load_state()
    token, source = state.resolve_openrouter_key_with_source(loaded)
    assert token == "token"
    assert source == "mattstash:openrouter.apikey"
    assert seen["cmd"][2] == "openrouter.apikey"


def test_resolve_openrouter_key_handles_errors(monkeypatch):
    monkeypatch.delenv("CAR_OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_PROVIDER_API_KEY", raising=False)

    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(state.subprocess, "run", boom)

    assert state.resolve_openrouter_key(state.CarState()) is None
    assert state.resolve_openrouter_key_with_source(state.CarState()) == (None, None)
    assert state.resolve_openrouter_key(
        state.CarState(mattstash_cli="", key_name="name")
    ) is None
    assert state.resolve_openrouter_key_with_source(
        state.CarState(mattstash_cli="", key_name="name")
    ) == (None, None)
    assert state.resolve_openrouter_key(
        state.CarState(mattstash_cli="m", key_name="")
    ) is None
    assert state.resolve_openrouter_key_with_source(
        state.CarState(mattstash_cli="m", key_name="")
    ) == (None, None)


def test_resolve_openrouter_key_rejects_bad_result(monkeypatch):
    monkeypatch.delenv("CAR_OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_PROVIDER_API_KEY", raising=False)

    completed = subprocess.CompletedProcess(
        args=["mattstash"], returncode=1, stdout="", stderr="err"
    )
    monkeypatch.setattr(state.subprocess, "run", lambda *a, **k: completed)

    assert state.resolve_openrouter_key(state.CarState()) is None


def test_state_path_uses_state_file(monkeypatch, tmp_path):
    f = tmp_path / "x.json"
    monkeypatch.setattr(state, "state_file", lambda: f)
    assert state.state_path() == f


def test_store_openrouter_key_success(monkeypatch):
    completed = subprocess.CompletedProcess(
        args=["mattstash"], returncode=0, stdout="ok\n", stderr=""
    )
    monkeypatch.setattr(state.subprocess, "run", lambda *a, **k: completed)

    s = state.CarState(mattstash_cli="mattstash", key_name="openrouter_api_key")
    assert state.store_openrouter_key(s, "tok") == "openrouter_api_key"
    assert state.store_openrouter_key(s, "tok", key_name="other") == "other"


def test_store_openrouter_key_validation_errors():
    s = state.CarState(mattstash_cli="", key_name="name")
    with pytest.raises(RuntimeError, match="not configured"):
        state.store_openrouter_key(s, "tok")

    s2 = state.CarState(mattstash_cli="m", key_name="")
    with pytest.raises(RuntimeError, match="not configured"):
        state.store_openrouter_key(s2, "tok")

    s3 = state.CarState(mattstash_cli="m", key_name="name")
    with pytest.raises(RuntimeError, match="empty"):
        state.store_openrouter_key(s3, " ")


def test_store_openrouter_key_runtime_errors(monkeypatch):
    s = state.CarState(mattstash_cli="m", key_name="name")

    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(state.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="not found"):
        state.store_openrouter_key(s, "tok")

    completed = subprocess.CompletedProcess(
        args=["m"], returncode=1, stdout="", stderr="denied"
    )
    monkeypatch.setattr(state.subprocess, "run", lambda *a, **k: completed)
    with pytest.raises(RuntimeError, match="mattstash put failed"):
        state.store_openrouter_key(s, "tok")


def test_state_from_dict_sanitizes_favorites_and_route_mode():
    result = state._state_from_dict({
        "favorite_models": "bad",
        "route_mode": "bad",
    })

    assert result.favorite_models == []
    assert result.route_mode == "model"
