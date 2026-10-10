"""Tests for the Python and mattstash handling in install.sh.

install.sh is sourced (without running ``main``) in a bash subprocess and its functions are
exercised against a fake ``mattstash`` executable and fake ``python3`` interpreters, so no real
mattstash database is touched and nothing is installed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required"),
]

INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"

FAKE_MATTSTASH = """#!/usr/bin/env bash
# Fake mattstash CLI. State lives next to the script.
here="$(cd "$(dirname "$0")" && pwd)"
printf '%s\\n' "$*" >>"$here/calls.log"

case "$1" in
  keys)
    [ -f "$here/initialized" ]
    exit $?
    ;;
  setup)
    if [ "${2:-}" = "--help" ]; then
      echo "usage: mattstash setup [-h] [--force]${FAKE_HELP_EXTRA:-}"
      exit 0
    fi
    rc="${FAKE_SETUP_RC:-0}"
    if [ "$rc" = "0" ]; then
      touch "$here/initialized"
    fi
    exit "$rc"
    ;;
esac
exit 99
"""


def _run_install_function(tmp_path: Path, body: str, env: dict[str, str] | None = None):
    """Source install.sh without ``main`` and run ``body`` with a fake mattstash CLI."""
    source = INSTALL_SH.read_text(encoding="utf-8")
    assert source.rstrip().endswith('main "$@"')
    functions_only = tmp_path / "install_functions.sh"
    functions_only.write_text(source.rstrip()[: -len('main "$@"')], encoding="utf-8")

    fake = tmp_path / "mattstash"
    fake.write_text(FAKE_MATTSTASH, encoding="utf-8")
    fake.chmod(0o755)

    script = f"""
set -euo pipefail
source "{functions_only}"
CAR_MATTSTASH_CLI="{fake}"
{body}
"""
    full_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LANG": "en_US.UTF-8",
    }
    full_env.update(env or {})
    result = subprocess.run(
        [shutil.which("bash") or "bash", "-c", script],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls_log = tmp_path / "calls.log"
    calls = calls_log.read_text(encoding="utf-8").splitlines() if calls_log.exists() else []
    return result, calls


INTERACTIVE = """
can_prompt() { return 0; }
prompt_yes_no() { return 0; }
"""

NON_INTERACTIVE = """
can_prompt() { return 1; }
prompt_yes_no() { return 1; }
"""

CALL_ENSURE = """
if ensure_mattstash_initialized; then echo RESULT=0; else echo "RESULT=$?"; fi
"""


def test_setup_uses_sidecar_when_cli_supports_it(tmp_path):
    result, calls = _run_install_function(
        tmp_path,
        INTERACTIVE + CALL_ENSURE,
        env={"FAKE_HELP_EXTRA": " [--sidecar] [--generate]"},
    )

    assert "RESULT=0" in result.stdout
    assert calls == ["keys", "setup --help", "setup --sidecar"]


def test_setup_without_sidecar_flag_for_older_cli(tmp_path):
    result, calls = _run_install_function(tmp_path, INTERACTIVE + CALL_ENSURE)

    assert "RESULT=0" in result.stdout
    assert calls == ["keys", "setup --help", "setup"]


def test_setup_skipped_when_already_initialized(tmp_path):
    (tmp_path / "initialized").write_text("", encoding="utf-8")

    result, calls = _run_install_function(tmp_path, INTERACTIVE + CALL_ENSURE)

    assert "RESULT=0" in result.stdout
    assert calls == ["keys"]


def test_setup_refusing_to_overwrite_is_reported_not_swallowed(tmp_path):
    result, calls = _run_install_function(
        tmp_path,
        INTERACTIVE + CALL_ENSURE,
        env={"FAKE_HELP_EXTRA": " [--sidecar]", "FAKE_SETUP_RC": "8"},
    )

    assert "RESULT=1" in result.stdout
    assert "refused to overwrite existing files" in result.stdout
    assert "KDBX_PASSWORD_FILE" in result.stdout
    assert calls[-1] == "setup --sidecar"


def test_setup_failure_is_reported_not_swallowed(tmp_path):
    result, _calls = _run_install_function(
        tmp_path,
        INTERACTIVE + CALL_ENSURE,
        env={"FAKE_HELP_EXTRA": " [--sidecar]", "FAKE_SETUP_RC": "7"},
    )

    assert "RESULT=1" in result.stdout
    assert "mattstash setup failed (exit 7)" in result.stdout


def test_non_interactive_prints_the_non_interactive_setup_command(tmp_path):
    result, calls = _run_install_function(
        tmp_path,
        NON_INTERACTIVE + CALL_ENSURE,
        env={"FAKE_HELP_EXTRA": " [--sidecar]"},
    )

    assert "RESULT=1" in result.stdout
    assert f"Run manually: {tmp_path / 'mattstash'} setup --sidecar" in result.stdout
    assert "setup --sidecar" not in calls  # printed for the user, never executed


def _fake_python(path: Path, version: str | None) -> Path:
    """Write a fake interpreter that reports ``version`` (or fails to run when ``None``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "exit 1" if version is None else f"printf '%s\\n' '{version}'"
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_tools_venv(venv: Path, version: str) -> Path:
    """Create a healthy-looking tools venv whose interpreter reports ``version``."""
    _fake_python(venv / "bin" / "python", version)
    pip = venv / "bin" / "pip"
    pip.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pip.chmod(0o755)
    return venv


def _host_python_env(tmp_path: Path, version: str | None) -> dict[str, str]:
    """PATH that resolves ``python3`` to a fake interpreter, ahead of the system ones."""
    _fake_python(tmp_path / "fakebin" / "python3", version)
    return {"PATH": f"{tmp_path / 'fakebin'}:/usr/bin:/bin"}


def test_default_package_is_0_2_whatever_the_host_python_is(tmp_path):
    # The Python version is checked up front instead; the pip spec never falls back to 0.1.x.
    result, _calls = _run_install_function(
        tmp_path,
        'printf "%s" "$CAR_MATTSTASH_PACKAGE"\n'
        "if type default_mattstash_package >/dev/null 2>&1; then printf ' fallback-still-defined'; fi",
        env=_host_python_env(tmp_path, "3.9.6"),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mattstash>=0.2,<0.3"


def test_package_override_is_respected(tmp_path):
    result, _calls = _run_install_function(
        tmp_path,
        'printf "%s" "$CAR_MATTSTASH_PACKAGE"',
        env={"CAR_MATTSTASH_PACKAGE": "mattstash==0.2.0"},
    )

    assert result.stdout == "mattstash==0.2.0"


CALL_REQUIRE_PYTHON = "require_supported_python; echo REACHED_AFTER_CHECK"


@pytest.mark.parametrize("version", ["3.11.0", "3.11.13", "3.12.9", "3.13.1", "3.20.0", "4.0.0"])
def test_supported_python_passes(tmp_path, version):
    result, _calls = _run_install_function(
        tmp_path, CALL_REQUIRE_PYTHON, env=_host_python_env(tmp_path, version)
    )

    assert result.returncode == 0, result.stderr
    assert "REACHED_AFTER_CHECK" in result.stdout
    assert f"Using Python {version}" in result.stdout


@pytest.mark.parametrize("version", ["3.10.14", "3.9.6", "3.8.0", "3.0.1", "2.7.18"])
def test_old_python_is_refused_with_a_clear_message(tmp_path, version):
    result, _calls = _run_install_function(
        tmp_path, CALL_REQUIRE_PYTHON, env=_host_python_env(tmp_path, version)
    )

    assert result.returncode == 1
    assert "REACHED_AFTER_CHECK" not in result.stdout
    assert f"Python 3.11 or newer is required (mattstash 0.2 and car need it), but python3 is Python {version}." in result.stderr
    assert "Install Python 3.11 or newer" in result.stderr


def test_real_interpreter_is_accepted(tmp_path):
    # The suite itself needs Python >= 3.11, so the interpreter running it must be accepted.
    bin_dir = tmp_path / "realbin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)

    result, _calls = _run_install_function(
        tmp_path, CALL_REQUIRE_PYTHON, env={"PATH": f"{bin_dir}:/usr/bin:/bin"}
    )

    assert result.returncode == 0, result.stderr
    assert "REACHED_AFTER_CHECK" in result.stdout


@pytest.mark.parametrize("version", [None, "", "not-a-version", "3"])
def test_unreadable_python_version_is_refused(tmp_path, version):
    result, _calls = _run_install_function(
        tmp_path,
        CALL_REQUIRE_PYTHON,
        env=_host_python_env(tmp_path, version),
    )

    assert result.returncode == 1
    assert "REACHED_AFTER_CHECK" not in result.stdout
    # An unrunnable interpreter prints nothing; a bogus one is refused as too old/unknown.
    assert "Python 3.11 or newer is required" in result.stderr


def test_existing_healthy_venv_on_old_python_is_refused(tmp_path):
    venv = _fake_tools_venv(tmp_path / "venv-tools", "3.9.6")

    # The host python3 is new enough, but the venv that would be reused is not.
    result, _calls = _run_install_function(
        tmp_path,
        CALL_REQUIRE_PYTHON,
        env={**_host_python_env(tmp_path, "3.12.1"), "CAR_TOOLS_VENV": str(venv)},
    )

    assert result.returncode == 1
    assert "REACHED_AFTER_CHECK" not in result.stdout
    assert f"the existing tools venv at {venv} is Python 3.9.6" in result.stderr
    assert f'rm -rf "{venv}"' in result.stderr


def test_existing_healthy_venv_on_new_python_is_accepted(tmp_path):
    venv = _fake_tools_venv(tmp_path / "venv-tools", "3.12.4")

    result, _calls = _run_install_function(
        tmp_path,
        CALL_REQUIRE_PYTHON,
        env={**_host_python_env(tmp_path, "3.12.1"), "CAR_TOOLS_VENV": str(venv)},
    )

    assert result.returncode == 0, result.stderr
    assert "Using Python 3.12.4" in result.stdout


def test_broken_venv_is_checked_against_the_host_python(tmp_path):
    # No pip: the venv is not healthy, so the installer would recreate it with python3.
    venv = tmp_path / "venv-tools"
    _fake_python(venv / "bin" / "python", "3.12.4")

    result, _calls = _run_install_function(
        tmp_path,
        CALL_REQUIRE_PYTHON,
        env={**_host_python_env(tmp_path, "3.10.9"), "CAR_TOOLS_VENV": str(venv)},
    )

    assert result.returncode == 1
    assert "but python3 is Python 3.10.9." in result.stderr


def test_python_is_checked_before_any_prompt_or_install_step(tmp_path):
    traced_main = """
require_cmd() { :; }
choose_install_mode() { echo PROMPTED; }
clone_or_update_repo() { echo CLONED; }
main --non-interactive
"""
    result, _calls = _run_install_function(
        tmp_path, traced_main, env=_host_python_env(tmp_path, "3.9.6")
    )

    assert result.returncode == 1
    assert "PROMPTED" not in result.stdout
    assert "CLONED" not in result.stdout
    assert "Python 3.11 or newer is required" in result.stderr


def _run_install_script(
    tmp_path: Path, args: list[str], python_version: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the real install.sh with fake git/curl/docker/python3 that only log their calls."""
    bin_dir = tmp_path / "fakebin"
    _fake_python(bin_dir / "python3", python_version)
    for name, rc in (("git", 0), ("curl", 0), ("docker", 1)):
        tool = bin_dir / name
        script = f"""#!/bin/sh
printf '{name} %s\\n' "$*" >>"{tmp_path}/tools.log"
exit {rc}
"""
        tool.write_text(script, encoding="utf-8")
        tool.chmod(0o755)

    result = subprocess.run(
        [shutil.which("bash") or "bash", str(INSTALL_SH), "--non-interactive", *args],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "en_US.UTF-8"},
        capture_output=True,
        text=True,
        check=False,
    )
    log = tmp_path / "tools.log"
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.mark.parametrize("mode", ["docker", "venv"])
def test_installer_stops_on_old_python_before_touching_anything(tmp_path, mode):
    result, tool_calls = _run_install_script(
        tmp_path, ["--mode", mode, "--harness", "copilot"], python_version="3.9.6"
    )

    assert result.returncode == 1
    assert "but python3 is Python 3.9.6." in result.stderr
    # No docker call, no clone, no harness download, nothing written to the home directory.
    assert tool_calls == []
    assert not (tmp_path / ".local").exists()
    assert not (tmp_path / ".bashrc").exists()
    assert not (tmp_path / ".zshrc").exists()


def test_docker_mode_installer_gets_past_the_python_check_on_a_supported_host(tmp_path):
    result, tool_calls = _run_install_script(
        tmp_path, ["--mode", "docker", "--harness", "copilot"], python_version="3.12.1"
    )

    # The fake docker daemon is "not running", which is the next step after the Python check.
    assert "Using Python 3.12.1 for the tools venv" in result.stdout
    assert "Docker daemon is not running" in result.stderr
    assert result.returncode == 1
    assert tool_calls == ["docker info"]
