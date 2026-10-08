"""Tests for the mattstash handling in install.sh.

install.sh is sourced (without running ``main``) in a bash subprocess and its functions are
exercised against a fake ``mattstash`` executable, so no real mattstash database is touched.
"""

from __future__ import annotations

import shutil
import subprocess
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


def _fake_python3(bin_dir: Path, exit_code: int) -> None:
    bin_dir.mkdir()
    python3 = bin_dir / "python3"
    python3.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    python3.chmod(0o755)


@pytest.mark.parametrize(
    ("python_exit", "expected"),
    [(0, "mattstash>=0.2,<0.3"), (1, "mattstash<0.2")],
)
def test_default_package_follows_host_python_version(tmp_path, python_exit, expected):
    bin_dir = tmp_path / "fakebin"
    _fake_python3(bin_dir, python_exit)

    result, _calls = _run_install_function(
        tmp_path,
        'printf "%s" "$CAR_MATTSTASH_PACKAGE"',
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


def test_default_package_without_python3_falls_back_to_pre_0_2(tmp_path):
    # PATH holds nothing at all, so there is no python3.
    bin_dir = tmp_path / "emptybin"
    bin_dir.mkdir()

    result, _calls = _run_install_function(
        tmp_path,
        'printf "%s" "$(default_mattstash_package)"',
        env={"PATH": str(bin_dir)},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mattstash<0.2"


def test_package_override_is_respected(tmp_path):
    result, _calls = _run_install_function(
        tmp_path,
        'printf "%s" "$CAR_MATTSTASH_PACKAGE"',
        env={"CAR_MATTSTASH_PACKAGE": "mattstash==0.2.0"},
    )

    assert result.stdout == "mattstash==0.2.0"
