from __future__ import annotations

import os
import shutil
import subprocess
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


def exec_copilot(
    args: list[str],
    env: dict[str, str],
    backend: str | None = None,
) -> int:
    if backend == "gh":
        cmd = ["gh", "copilot", *args]
    elif backend == "copilot":
        cmd = ["copilot", *args]
    elif shutil.which("copilot"):
        cmd = ["copilot", *args]
    else:
        cmd = ["gh", "copilot", *args]

    try:
        result = subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        print("Copilot executable was not found.")
        return 1
    return result.returncode


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


def exec_claude(
    args: list[str],
    env: dict[str, str],
) -> int:
    cmd = ["claude", *args]
    try:
        result = subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        print("Claude Code executable was not found.")
        return 1
    return result.returncode


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