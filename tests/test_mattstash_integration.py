from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from car import cli, state
from car.state import CarState


class _Console:
    def __init__(self):
        self.messages = []

    def print(self, *args, **kwargs):
        self.messages.append((args, kwargs))


@pytest.mark.integration
def test_mattstash_set_then_verify_flow(monkeypatch, tmp_path):
    store_file = tmp_path / "store.txt"
    mattstash_cli = _write_fake_mattstash(tmp_path, store_file, mode="plain")

    st = CarState(
        mattstash_cli=str(mattstash_cli),
        key_name="openrouter_api_key",
        openrouter_base_url="https://openrouter.ai/api/v1",
    )

    key_name = state.store_openrouter_key(st, "tok-123")
    assert key_name == "openrouter_api_key"

    token, source = state.resolve_openrouter_key_with_source(st)
    assert token == "tok-123"
    assert source == "mattstash:openrouter_api_key"

    seen = {"token": None}

    def fake_verify(_base_url, api_key):
        seen["token"] = api_key
        return {"data": {"label": "test", "usage": 0}}

    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "verify_api_key", fake_verify)

    rc = cli.handle_key(st, argparse.Namespace(action="verify"))
    assert rc == 0
    assert seen["token"] == "tok-123"


@pytest.mark.integration
def test_mattstash_mutating_readback_is_detected(tmp_path):
    store_file = tmp_path / "store.txt"
    mattstash_cli = _write_fake_mattstash(tmp_path, store_file, mode="masked")

    st = CarState(
        mattstash_cli=str(mattstash_cli),
        key_name="openrouter_api_key",
    )

    with pytest.raises(RuntimeError, match="does not match input"):
        state.store_openrouter_key(st, "tok-123")


def _write_fake_mattstash(tmp_path: Path, store_file: Path, mode: str) -> Path:
    script = tmp_path / "mattstash"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

store = pathlib.Path(sys.argv[0]).with_name("store.txt")
mode = pathlib.Path(sys.argv[0]).with_name("mode.txt").read_text(encoding="utf-8").strip()

args = sys.argv[1:]
if not args:
    sys.exit(1)

if args[0] == "put":
    if len(args) < 4 or args[2] != "--value":
        sys.exit(2)
    key = args[1]
    value = args[3]
    store.write_text(f"{key}\\n{value}\\n", encoding="utf-8")
    print(f"{key}: *****")
    sys.exit(0)

if args[0] == "get":
    if len(args) < 3 or args[2] != "--show-password":
        sys.exit(2)
    as_json = "--json" in args
    key = args[1]
    if not store.exists():
        sys.exit(1)
    stored_key, stored_value = store.read_text(encoding="utf-8").splitlines()
    if stored_key != key:
        sys.exit(1)
    if mode == "masked":
        value = "*****"
    else:
        value = stored_value
    if as_json:
        print('{"name": "%s", "version": "0000000001", "value": "%s", "notes": null}' % (key, value))
    else:
        print(key)
        print("  value: %s" % value)
    sys.exit(0)

sys.exit(1)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    script.with_name("mode.txt").write_text(mode, encoding="utf-8")
    return script
