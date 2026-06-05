from __future__ import annotations

import subprocess

from car import harness


def test_check_gh_installed_found(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/bin/gh")
    result = harness.check_gh_installed()
    assert result.ok is True
    assert "/usr/bin/gh" in result.detail


def test_check_gh_installed_not_found(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda _: None)
    result = harness.check_gh_installed()
    assert result.ok is False


def test_check_copilot_extension_found(monkeypatch):
    done = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout="github/gh-copilot",
        stderr="",
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: done)
    assert harness.check_copilot_extension().ok is True


def test_check_copilot_extension_missing(monkeypatch):
    done = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout="other/ext",
        stderr="",
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: done)
    assert harness.check_copilot_extension().ok is False


def test_check_copilot_extension_error_stderr(monkeypatch):
    err = subprocess.CompletedProcess(
        args=["gh"],
        returncode=1,
        stdout="",
        stderr="nope",
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: err)
    assert not harness.check_copilot_extension().ok
    assert "nope" in harness.check_copilot_extension().detail


def test_check_copilot_extension_file_not_found(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(harness.subprocess, "run", boom)
    result = harness.check_copilot_extension()
    assert not result.ok
    assert "gh not found" in result.detail


def test_check_gh_auth_ok(monkeypatch):
    ok = subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: ok)
    assert harness.check_gh_auth().ok is True


def test_check_gh_auth_bad(monkeypatch):
    bad = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr="login"
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: bad)
    result = harness.check_gh_auth()
    assert not result.ok
    assert "login" in result.detail


def test_check_gh_auth_no_stderr_shows_help(monkeypatch):
    bad = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr=""
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: bad)
    assert "Run gh auth login" in harness.check_gh_auth().detail


def test_check_gh_auth_file_not_found(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(harness.subprocess, "run", boom)
    result = harness.check_gh_auth()
    assert not result.ok
    assert "gh not found" in result.detail


def test_check_claude_installed_found(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/bin/claude")
    result = harness.check_claude_installed()
    assert result.ok is True
    assert "/usr/bin/claude" in result.detail


def test_check_claude_installed_not_found(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda _: None)
    result = harness.check_claude_installed()
    assert result.ok is False
    assert "Claude Code CLI not found" in result.detail


def test_copilot_env(monkeypatch):
    monkeypatch.setenv("SENTINEL", "1")
    env = harness.copilot_env("u", "k", "m")
    assert env["SENTINEL"] == "1"
    assert env["COPILOT_PROVIDER_BASE_URL"] == "u"
    assert env["COPILOT_PROVIDER_API_KEY"] == "k"
    assert env["COPILOT_MODEL"] == "m"


def test_claude_env(monkeypatch):
    monkeypatch.setenv("SENTINEL", "1")
    env = harness.claude_env("u", "k", "m")
    assert env["SENTINEL"] == "1"
    assert env["ANTHROPIC_BASE_URL"] == "u"
    assert env["ANTHROPIC_API_KEY"] == "k"
    assert env["ANTHROPIC_MODEL"] == "m"


def test_exec_copilot_paths(monkeypatch):
    seen: dict[str, list[str]] = {"cmd": []}

    def fake_execvpe(file, args, env):
        seen["cmd"] = list(args)
        return None  # execvpe does not return

    monkeypatch.setattr(harness.os, "execvpe", fake_execvpe)

    # Prefer standalone copilot
    monkeypatch.setattr(
        harness.shutil, "which",
        lambda name: "/usr/bin/copilot" if name == "copilot" else None,
    )
    harness.exec_copilot(["suggest"], {"A": "1"})
    assert seen["cmd"][0] == "copilot"

    # Fall back to gh copilot
    monkeypatch.setattr(harness.shutil, "which", lambda _: None)
    harness.exec_copilot(["suggest"], {"A": "1"})
    assert seen["cmd"][:2] == ["gh", "copilot"]

    # Explicit backend gh
    harness.exec_copilot(["suggest"], {"A": "1"}, backend="gh")
    assert seen["cmd"][:2] == ["gh", "copilot"]

    # Explicit backend copilot
    harness.exec_copilot(
        ["suggest"], {"A": "1"}, backend="copilot",
    )
    assert seen["cmd"][0] == "copilot"


def test_exec_copilot_file_not_found(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(harness.os, "execvpe", boom)
    monkeypatch.setattr(harness.shutil, "which", lambda _: None)
    assert harness.exec_copilot(["suggest"], {}) == 1


def test_exec_claude(monkeypatch):
    seen = {"cmd": None, "cleaned": False}
    ok = subprocess.CompletedProcess(args=["claude"], returncode=3)

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return ok

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    monkeypatch.setattr(
        harness,
        "_restore_terminal_state",
        lambda: seen.update({"cleaned": True}),
    )

    assert harness.exec_claude(["chat"], {"A": "1"}) == 3
    assert seen["cmd"] == ["claude", "chat"]
    assert seen["cleaned"] is True


def test_exec_claude_file_not_found(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(harness.subprocess, "run", boom)
    assert harness.exec_claude([], {}) == 1


def test_exec_claude_oserror(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(harness.subprocess, "run", boom)
    assert harness.exec_claude([], {}) == 1


def test_exec_claude_keyboard_interrupt(monkeypatch):
    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(harness.subprocess, "run", boom)
    assert harness.exec_claude([], {}) == 130


def test_detect_available_harnesses_both(monkeypatch):
    monkeypatch.setattr(
        harness.shutil, "which",
        lambda name: {
            "gh": "/usr/bin/gh",
            "copilot": "/usr/bin/copilot",
            "claude": "/usr/bin/claude",
        }.get(name),
    )
    done = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout="github/gh-copilot",
        stderr="",
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: done)

    result = harness.detect_available_harnesses()
    assert "copilot" in result
    assert "claude" in result


def test_detect_available_harnesses_claude_only(monkeypatch):
    monkeypatch.setattr(
        harness.shutil, "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )
    # gh not available, so _copilot_extension_present won't be called
    result = harness.detect_available_harnesses()
    assert result == ["claude"]


def test_detect_available_harnesses_none(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda _: None)
    # _copilot_extension_present will catch FileNotFoundError
    result = harness.detect_available_harnesses()
    assert result == []


def test_detect_copilot_standalone_no_gh(monkeypatch):
    monkeypatch.setattr(
        harness.shutil, "which",
        lambda name: "/usr/bin/copilot" if name == "copilot" else None,
    )
    done = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout="",
        stderr="",
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: done)
    result = harness.detect_available_harnesses()
    # standalone copilot binary is detected even if gh missing
    assert result == ["copilot"]


def test_copilot_extension_present_file_not_found(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(harness.subprocess, "run", boom)
    assert harness._copilot_extension_present() is False


def test_copilot_extension_present_bad_rc(monkeypatch):
    bad = subprocess.CompletedProcess(
        args=["gh"],
        returncode=1,
        stdout="",
        stderr="",
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: bad)
    assert harness._copilot_extension_present() is False


def test_copilot_extension_present_gh_copilot_in_output(monkeypatch):
    done = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout="gh-copilot",
        stderr="",
    )
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: done)
    assert harness._copilot_extension_present() is True


def test_build_harness_env_copilot(monkeypatch):
    monkeypatch.setenv("X", "y")
    env = harness.build_harness_env("copilot", "url", "key", "model")
    assert env["COPILOT_PROVIDER_BASE_URL"] == "url"
    assert env["COPILOT_PROVIDER_API_KEY"] == "key"
    assert env["COPILOT_MODEL"] == "model"
    assert "ANTHROPIC_BASE_URL" not in env


def test_build_harness_env_claude(monkeypatch):
    monkeypatch.setenv("X", "y")
    env = harness.build_harness_env("claude", "url", "key", "model")
    assert env["ANTHROPIC_BASE_URL"] == "url"
    assert env["ANTHROPIC_API_KEY"] == "key"
    assert env["ANTHROPIC_MODEL"] == "model"
    assert "COPILOT_PROVIDER_BASE_URL" not in env


def test_exec_harness_dispatches(monkeypatch):
    seen = {"harness": None}

    def fake_copilot(args, env, backend=None):
        seen["harness"] = "copilot"
        return 42

    def fake_claude(args, env):
        seen["harness"] = "claude"
        return 43

    monkeypatch.setattr(harness, "exec_copilot", fake_copilot)
    monkeypatch.setattr(harness, "exec_claude", fake_claude)

    assert harness.exec_harness("copilot", [], {}) == 42
    assert seen["harness"] == "copilot"
    assert harness.exec_harness("claude", [], {}) == 43
    assert seen["harness"] == "claude"


def test_harness_display_name():
    assert harness.harness_display_name("copilot") == (
        "Copilot CLI (gh-copilot)"
    )
    assert harness.harness_display_name("claude") == "Claude Code CLI"
    assert harness.harness_display_name("unknown") == "unknown"  # type: ignore[arg-type]