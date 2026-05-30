from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class DoctorResult:
    name: str
    ok: bool
    detail: str


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
        return DoctorResult("gh-copilot", False, result.stderr.strip() or "unable to read extensions")

    output = result.stdout.lower()
    if "github/gh-copilot" in output or "gh-copilot" in output:
        return DoctorResult("gh-copilot", True, "Extension installed")

    return DoctorResult("gh-copilot", False, "Install with: gh extension install github/gh-copilot")


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

    return DoctorResult("gh-auth", False, result.stderr.strip() or "Run gh auth login")


def copilot_env(base_url: str, api_key: str, model_id: str) -> dict[str, str]:
    env = os.environ.copy()
    env["COPILOT_PROVIDER_BASE_URL"] = base_url
    env["COPILOT_PROVIDER_API_KEY"] = api_key
    env["COPILOT_MODEL"] = model_id
    return env


def exec_copilot(args: list[str], env: dict[str, str]) -> int:
    cmd = ["gh", "copilot", *args]
    try:
        result = subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        print("gh executable was not found.")
        return 1
    return result.returncode
