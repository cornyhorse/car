from __future__ import annotations

from car import tui


class _FakeApp:
    def __init__(self, models, selected_model, provider_lock):
        self.models = models
        self.selected_model = selected_model
        self.provider_lock = provider_lock

    def run(self):
        return ("picked/model", "aws-bedrock")


def test_fmt_price():
    assert tui._fmt_price(None) == "-"
    assert tui._fmt_price(1.23456) == "1.2346"


def test_run_tui(monkeypatch):
    monkeypatch.setattr(tui, "CarTui", _FakeApp)
    result = tui.run_tui([], "a/b", None)
    assert result == ("picked/model", "aws-bedrock")


def test_model_picked_message_fields():
    msg = tui.ModelPicked("m/x", "openai")
    assert msg.model_id == "m/x"
    assert msg.provider == "openai"
