from __future__ import annotations

import subprocess

from car import copilot
from car import harness as _harness


def test_check_gh_installed(monkeypatch):
    monkeypatch.setattr(_harness.shutil, "which", lambda _: "/usr/bin/gh")
    ok = copilot.check_gh_installed()
    assert ok.ok is True

    monkeypatch.setattr(_harness.shutil, "which", lambda _: None)
    bad = copilot.check_gh_installed()
    assert bad.ok is False


def test_check_copilot_extension(monkeypatch):
    done = subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout="github/gh-copilot", stderr=""
    )
    monkeypatch.setattr(_harness.subprocess, "run", lambda *a, **k: done)
    assert copilot.check_copilot_extension().ok is True

    missing = subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout="other/ext", stderr=""
    )
    monkeypatch.setattr(_harness.subprocess, "run", lambda *a, **k: missing)
    assert copilot.check_copilot_extension().ok is False

    err = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr="nope"
    )
    monkeypatch.setattr(_harness.subprocess, "run", lambda *a, **k: err)
    assert copilot.check_copilot_extension().detail == "nope"

    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(_harness.subprocess, "run", boom)
    assert copilot.check_copilot_extension().detail == "gh not found"


def test_check_gh_auth(monkeypatch):
    ok = subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout="", stderr="",
    )
    monkeypatch.setattr(_harness.subprocess, "run", lambda *a, **k: ok)
    assert copilot.check_gh_auth().ok is True

    bad = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr="login"
    )
    monkeypatch.setattr(_harness.subprocess, "run", lambda *a, **k: bad)
    assert copilot.check_gh_auth().detail == "login"

    bad2 = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr="",
    )
    monkeypatch.setattr(_harness.subprocess, "run", lambda *a, **k: bad2)
    assert "Run gh auth login" in copilot.check_gh_auth().detail

    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(_harness.subprocess, "run", boom)
    assert copilot.check_gh_auth().detail == "gh not found"


def test_copilot_env_sets_variables(monkeypatch):
    monkeypatch.setenv("SENTINEL", "1")
    out = copilot.copilot_env("u", "k", "m")
    assert out["SENTINEL"] == "1"
    assert out["COPILOT_PROVIDER_BASE_URL"] == "u"
    assert out["COPILOT_PROVIDER_API_KEY"] == "k"
    assert out["COPILOT_MODEL"] == "m"


def test_exec_copilot(monkeypatch):
    seen = {"file": None, "cmd": None, "env": None}

    class _ExecCalled(Exception):
        pass

    def fake_exec(file, cmd, env):
        seen["file"] = file
        seen["cmd"] = cmd
        seen["env"] = env
        raise _ExecCalled

    monkeypatch.setattr(
        _harness.shutil, "which",
        lambda name: "/usr/bin/copilot" if name == "copilot" else None,
    )
    monkeypatch.setattr(_harness.os, "execvpe", fake_exec)
    try:
        copilot.exec_copilot(["suggest"], {"A": "1"})
    except _ExecCalled:
        pass
    assert seen["cmd"][0] == "copilot"
    assert seen["file"] == "copilot"
    assert seen["env"] == {"A": "1"}

    monkeypatch.setattr(_harness.shutil, "which", lambda _name: None)
    try:
        copilot.exec_copilot(["suggest"], {"A": "1"})
    except _ExecCalled:
        pass
    assert seen["cmd"][:2] == ["gh", "copilot"]

    try:
        copilot.exec_copilot(["suggest"], {"A": "1"}, backend="gh")
    except _ExecCalled:
        pass
    assert seen["cmd"][:2] == ["gh", "copilot"]

    try:
        copilot.exec_copilot(
            ["suggest"], {"A": "1"}, backend="copilot",
        )
    except _ExecCalled:
        pass
    assert seen["cmd"][0] == "copilot"

    def boom(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(_harness.os, "execvpe", boom)
    assert copilot.exec_copilot([], {}) == 1
