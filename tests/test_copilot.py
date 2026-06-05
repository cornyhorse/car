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
    ok = subprocess.CompletedProcess(args=["gh"], returncode=7)
    seen = {"cmd": None}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return ok

    monkeypatch.setattr(
        _harness.shutil, "which",
        lambda name: "/usr/bin/copilot" if name == "copilot" else None,
    )
    monkeypatch.setattr(_harness.subprocess, "run", fake_run)
    assert copilot.exec_copilot(["suggest"], {"A": "1"}) == 7
    assert seen["cmd"][0] == "copilot"

    monkeypatch.setattr(_harness.shutil, "which", lambda _name: None)
    assert copilot.exec_copilot(["suggest"], {"A": "1"}) == 7
    assert seen["cmd"][:2] == ["gh", "copilot"]

    assert copilot.exec_copilot(["suggest"], {"A": "1"}, backend="gh") == 7
    assert seen["cmd"][:2] == ["gh", "copilot"]

    assert copilot.exec_copilot(
        ["suggest"], {"A": "1"}, backend="copilot",
    ) == 7
    assert seen["cmd"][0] == "copilot"

    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(_harness.subprocess, "run", boom)
    assert copilot.exec_copilot([], {}) == 1
