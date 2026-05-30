from __future__ import annotations

from car import tui


class _FakeApp:
    def __init__(self, models, selected_model, provider_lock, favorite_models, route_mode):
        self.models = models
        self.selected_model = selected_model
        self.provider_lock = provider_lock
        self.favorite_models = favorite_models
        self.route_mode = route_mode

    def run(self):
        return ("picked/model", "aws-bedrock", "provider", ["picked/model"])


def test_fmt_price():
    assert tui._fmt_price(None) == "-"
    assert tui._fmt_price(1.23456) == "1.2346"


def test_run_tui(monkeypatch):
    monkeypatch.setattr(tui, "CarTui", _FakeApp)
    result = tui.run_tui([], "a/b", None, ["a/b"], "model")
    assert result == ("picked/model", "aws-bedrock", "provider", ["picked/model"])


def test_model_picked_message_fields():
    msg = tui.ModelPicked("m/x", "openai")
    assert msg.model_id == "m/x"
    assert msg.provider == "openai"
