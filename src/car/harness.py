from __future__ import annotations

import errno
import os
import pty
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

HarnessName = Literal["copilot", "claude"]
ALL_HARNESSES: list[HarnessName] = ["copilot", "claude"]


@dataclass
class DoctorResult:
    name: str
    ok: bool
    detail: str


# ── Copilot harness ──────────────────────────────────────────────────────────


def check_gh_installed() -> DoctorResult:
    gh_path = shutil.which("gh")
    if not gh_path:
        return DoctorResult("gh", False, "GitHub CLI not found in PATH")
    return DoctorResult("gh", True, f"Found at {gh_path}")


def check_copilot_extension() -> DoctorResult:
    try:
        result = subprocess.run(
            ["gh", "extension", "list"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return DoctorResult("gh-copilot", False, "gh not found")

    if result.returncode != 0:
        return DoctorResult(
            "gh-copilot", False,
            result.stderr.strip() or "unable to read extensions",
        )

    output = result.stdout.lower()
    if "github/gh-copilot" in output or "gh-copilot" in output:
        return DoctorResult("gh-copilot", True, "Extension installed")

    return DoctorResult(
        "gh-copilot", False,
        "Install with: gh extension install github/gh-copilot",
    )


def check_gh_auth() -> DoctorResult:
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return DoctorResult("gh-auth", False, "gh not found")

    if result.returncode == 0:
        return DoctorResult("gh-auth", True, "GitHub auth available")

    return DoctorResult(
        "gh-auth", False,
        result.stderr.strip() or "Run gh auth login",
    )


def copilot_env(base_url: str, api_key: str, model_id: str) -> dict[str, str]:
    env = os.environ.copy()
    env["COPILOT_PROVIDER_BASE_URL"] = base_url
    env["COPILOT_PROVIDER_API_KEY"] = api_key
    env["COPILOT_MODEL"] = model_id
    return env


def _copilot_cmd(backend: str | None = None) -> list[str]:
    """Return the copilot command list without args (for resolution)."""
    if backend == "gh":
        return ["gh", "copilot"]
    if backend == "copilot":
        return ["copilot"]
    if shutil.which("copilot"):
        return ["copilot"]
    return ["gh", "copilot"]


def exec_copilot(
    args: list[str],
    env: dict[str, str],
    backend: str | None = None,
) -> int:
    """Replace the current process with Copilot CLI.

    Uses os.execvpe to give the harness full terminal control (raw mode,
    alternate screen buffer, cursor handling). This function never returns
    on success — the Python process is replaced entirely.
    """
    cmd = [*_copilot_cmd(backend), *args]
    try:
        os.execvpe(cmd[0], cmd, env)
    except FileNotFoundError:
        print("Copilot executable was not found.")
        return 1
    except OSError as exc:
        print(f"Copilot executable failed to start: {exc}")
        return 1
    return 1  # pragma: no cover — os.execvpe never returns on success


# ── Claude Code harness ──────────────────────────────────────────────────────


def check_claude_installed() -> DoctorResult:
    claude_path = shutil.which("claude")
    if not claude_path:
        return DoctorResult(
            "claude", False, "Claude Code CLI not found in PATH"
        )
    return DoctorResult("claude", True, f"Found at {claude_path}")


def claude_env(base_url: str, api_key: str, model_id: str) -> dict[str, str]:
    env = os.environ.copy()
    # ANTHROPIC_BASE_URL overrides the API endpoint (points at OpenRouter).
    # ANTHROPIC_API_KEY is the bearer token Claude Code sends to that endpoint.
    # ANTHROPIC_MODEL selects the model; Claude Code reads this env var
    # directly (verified against Claude Code CLI docs).
    env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_MODEL"] = model_id
    return env


def _restore_terminal_state() -> None:
    # Best-effort cleanup after interactive PTY/TUI sessions.
    # We reset terminal attributes but deliberately do NOT clear the
    # screen — that would wipe harness output the user wants to see.
    try:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
    except Exception:  # pragma: no cover
        pass

    for cmd in (
        ["stty", "sane"],
        ["tput", "sgr0"],
        ["tput", "cnorm"],
    ):
        try:
            subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:  # pragma: no cover
            continue


def _run_in_pty(cmd: list[str], env: dict[str, str]) -> int:
    """Run *cmd* in a PTY with explicit environment variables.

    Uses `/usr/bin/env` semantics via `env` command so we keep pty.spawn's
    interactive relay behavior while still applying explicit overrides.
    """
    env_cmd = ["env", *[f"{k}={v}" for k, v in env.items()], *cmd]
    status = pty.spawn(env_cmd)

    try:
        return os.waitstatus_to_exitcode(status)
    except AttributeError:  # pragma: no cover — Python < 3.9 fallback
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return 128 + os.WTERMSIG(status)
        return 1


def exec_claude(
    args: list[str],
    env: dict[str, str],
) -> int:
    """Run Claude Code CLI in a fresh PTY and restore terminal state."""
    cmd = ["claude", *args]
    try:
        return _run_in_pty(cmd, env)
    except FileNotFoundError:
        print("Claude Code executable was not found.")
        return 1
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"Claude Code executable failed to start: {exc}")
        return 1
    finally:
        _restore_terminal_state()


# ── Harness detection & dispatch ─────────────────────────────────────────────


def detect_available_harnesses() -> list[HarnessName]:
    available: list[HarnessName] = []

    if shutil.which("gh") and _copilot_extension_present():
        available.append("copilot")
    elif shutil.which("copilot"):
        available.append("copilot")

    if shutil.which("claude"):
        available.append("claude")

    return available


def _copilot_extension_present() -> bool:
    try:
        result = subprocess.run(
            ["gh", "extension", "list"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    output = result.stdout.lower()
    return "github/gh-copilot" in output or "gh-copilot" in output


def build_harness_env(
    harness: HarnessName,
    base_url: str,
    api_key: str,
    model_id: str,
) -> dict[str, str]:
    if harness == "copilot":
        return copilot_env(base_url, api_key, model_id)
    return claude_env(base_url, api_key, model_id)


def exec_harness(
    harness: HarnessName,
    args: list[str],
    env: dict[str, str],
    backend: str | None = None,
) -> int:
    if harness == "copilot":
        return exec_copilot(args, env, backend=backend)
    return exec_claude(args, env)


def harness_display_name(harness: HarnessName) -> str:
    names: dict[HarnessName, str] = {
        "copilot": "Copilot CLI (gh-copilot)",
        "claude": "Claude Code CLI",
    }
    return names.get(harness, harness)