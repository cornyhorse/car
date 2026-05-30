from __future__ import annotations

import runpy

import car
import pytest


def test_version_constant():
    assert car.__version__ == "0.1.0"


def test_module_main_calls_cli_main(monkeypatch):
    called = {"n": 0}

    def fake_main():
        called["n"] += 1
        return 0

    monkeypatch.setattr("car.cli.main", fake_main)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("car", run_name="__main__")

    assert exc.value.code == 0
    assert called["n"] == 1
