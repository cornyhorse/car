from __future__ import annotations

import argparse

from car import cli
from car.openrouter import ModelEntry, OpenRouterError
from car.state import CarState


class _Console:
    def __init__(self):
        self.messages = []

    def print(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class _Check:
    def __init__(self, name, ok, detail):
        self.name = name
        self.ok = ok
        self.detail = detail


def _args(**kwargs):
    return argparse.Namespace(**kwargs)


def test_build_parser_parses_model_use():
    parser = cli.build_parser()
    ns = parser.parse_args(["model", "use", "x/y"])
    assert ns.command == "model"
    assert ns.action == "use"
    assert ns.model_id == "x/y"


def test_main_routes_no_args(monkeypatch):
    monkeypatch.setattr(cli, "launch_copilot", lambda args: 7)
    assert cli.main([]) == 7


def test_main_routes_subcommand(monkeypatch):
    monkeypatch.setattr(cli, "dispatch_subcommand", lambda args: 8)
    assert cli.main(["env"]) == 8


def test_main_routes_passthrough(monkeypatch):
    received = {"args": None}

    def fake_launch(args):
        received["args"] = args
        return 9

    monkeypatch.setattr(cli, "launch_copilot", fake_launch)
    assert cli.main(["suggest", "hello"]) == 9
    assert received["args"] == ["suggest", "hello"]


def test_dispatch_subcommand_all_branches(monkeypatch):
    st = CarState()
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "handle_model", lambda state, args: 1)
    monkeypatch.setattr(cli, "handle_provider", lambda state, args: 2)
    monkeypatch.setattr(cli, "handle_env", lambda state: 3)
    monkeypatch.setattr(cli, "handle_doctor", lambda state: 4)
    monkeypatch.setattr(cli, "handle_tui", lambda state: 5)
    monkeypatch.setattr(cli, "handle_config", lambda: 6)

    assert cli.dispatch_subcommand(_args(command="model")) == 1
    assert cli.dispatch_subcommand(_args(command="provider")) == 2
    assert cli.dispatch_subcommand(_args(command="env")) == 3
    assert cli.dispatch_subcommand(_args(command="doctor")) == 4
    assert cli.dispatch_subcommand(_args(command="tui")) == 5
    assert cli.dispatch_subcommand(_args(command="config")) == 6
    assert cli.dispatch_subcommand(_args(command="other")) == 1


def test_handle_model_list_from_cache(monkeypatch):
    st = CarState(provider_lock="openai")
    rows = [ModelEntry("openai/gpt", "openai", 1.0, 2.0, 3)]
    seen = {"printed": False}

    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))
    monkeypatch.setattr(cli, "filter_models", lambda r, p: r)

    def fake_print_models(*args, **kwargs):
        seen["printed"] = True

    monkeypatch.setattr(cli, "print_models", fake_print_models)

    assert cli.handle_model(st, _args(action="list")) == 0
    assert seen["printed"] is True


def test_handle_model_list_refresh_on_empty(monkeypatch):
    st = CarState(openrouter_base_url="u")
    rows = [ModelEntry("a/b", "a", None, None, None)]

    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))
    monkeypatch.setattr(cli, "refresh_models", lambda url: rows)
    monkeypatch.setattr(cli, "filter_models", lambda r, p: r)
    monkeypatch.setattr(cli, "print_models", lambda *a, **k: None)

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    assert cli.handle_model(st, _args(action="list")) == 0
    assert any("Model cache missing" in str(args[0]) for args, _ in c.messages)


def test_handle_model_list_refresh_failure(monkeypatch):
    st = CarState(openrouter_base_url="u")

    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))

    def boom(url):
        raise OpenRouterError("nope")

    monkeypatch.setattr(cli, "refresh_models", boom)

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    assert cli.handle_model(st, _args(action="list")) == 1


def test_handle_model_refresh_success_and_failure(monkeypatch):
    st = CarState(openrouter_base_url="u")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "refresh_models", lambda url: [1, 2])
    assert cli.handle_model(st, _args(action="refresh")) == 0

    def boom(url):
        raise OpenRouterError("x")

    monkeypatch.setattr(cli, "refresh_models", boom)
    assert cli.handle_model(st, _args(action="refresh")) == 1


def test_handle_model_use_current_unknown(monkeypatch):
    st = CarState(default_model="d")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    saved = {"called": False}

    def fake_save(state):
        saved["called"] = True

    monkeypatch.setattr(cli, "save_state", fake_save)

    assert cli.handle_model(st, _args(action="use", model_id="a/b")) == 0
    assert saved["called"] is True
    assert st.selected_model == "a/b"

    assert cli.handle_model(st, _args(action="current")) == 0
    assert cli.handle_model(st, _args(action="nope")) == 1


def test_handle_provider_branches(monkeypatch):
    st = CarState()
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "save_state", lambda state: None)

    assert cli.handle_provider(st, _args(action="lock", provider="aws-bedrock")) == 0
    assert st.provider_lock == "aws-bedrock"

    assert cli.handle_provider(st, _args(action="mode", value="prefer")) == 0
    assert st.provider_lock_mode == "prefer"

    assert cli.handle_provider(st, _args(action="unlock")) == 0
    assert st.provider_lock is None

    assert cli.handle_provider(st, _args(action="current")) == 0
    assert cli.handle_provider(st, _args(action="unknown")) == 1


def test_handle_env(monkeypatch):
    st = CarState(selected_model="a/b", provider_lock="aws", key_helper="helper")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    assert cli.handle_env(st) == 0

    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)
    assert cli.handle_env(st) == 0
    assert any("Hint: run helper" in str(args[0]) for args, _ in c.messages)


def test_handle_env_without_helper_does_not_print_hint(monkeypatch):
    st = CarState(selected_model="a/b", provider_lock="aws", key_helper="")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)

    assert cli.handle_env(st) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Hint: run" not in text_blob


def test_handle_doctor_success_and_failure(monkeypatch):
    st = CarState()
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "check_gh_installed", lambda: _Check("gh", True, "ok"))
    monkeypatch.setattr(cli, "check_copilot_extension", lambda: _Check("ext", True, "ok"))
    monkeypatch.setattr(cli, "check_gh_auth", lambda: _Check("auth", True, "ok"))
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "k")
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([1], "now"))
    assert cli.handle_doctor(st) == 0

    monkeypatch.setattr(cli, "check_gh_installed", lambda: _Check("gh", False, "bad"))
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))
    assert cli.handle_doctor(st) == 1


def test_handle_tui_paths(monkeypatch):
    st = CarState(openrouter_base_url="u", provider_lock="aws")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    rows = [ModelEntry("a/b", "a", None, None, None)]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))
    monkeypatch.setattr(cli, "run_tui", lambda *a: None)
    assert cli.handle_tui(st) == 0

    monkeypatch.setattr(cli, "run_tui", lambda *a: ("x/y", "openai"))
    saved = {"called": False}
    monkeypatch.setattr(
        cli,
        "save_state",
        lambda state: saved.update({"called": True}),
    )
    assert cli.handle_tui(st) == 0
    assert st.selected_model == "x/y"
    assert st.provider_lock == "openai"
    assert saved["called"] is True


def test_handle_tui_refresh_paths(monkeypatch):
    st = CarState(openrouter_base_url="u")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))
    monkeypatch.setattr(
        cli,
        "refresh_models",
        lambda base_url: [ModelEntry("a/b", "a", None, None, None)],
    )
    monkeypatch.setattr(cli, "run_tui", lambda *a: None)
    assert cli.handle_tui(st) == 0

    def boom(base_url):
        raise OpenRouterError("bad")

    monkeypatch.setattr(cli, "refresh_models", boom)
    assert cli.handle_tui(st) == 1


def test_handle_config(monkeypatch):
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "state_path", lambda: "x/y/z")
    assert cli.handle_config() == 0
    assert "x/y/z" in str(c.messages[-1][0][0])


def test_launch_copilot_paths(monkeypatch):
    st = CarState(selected_model="m", provider_lock="aws", provider_lock_mode="prefer")
    monkeypatch.setattr(cli, "load_state", lambda: st)

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)
    assert cli.launch_copilot([]) == 1

    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    monkeypatch.setattr(cli, "ensure_models_fresh", lambda state: None)
    monkeypatch.setattr(cli, "selected_model", lambda state: "model/x")
    monkeypatch.setattr(cli, "copilot_env", lambda *a: {})

    seen = {"args": None, "env": None}

    def fake_exec(args, env):
        seen["args"] = args
        seen["env"] = env
        return 0

    monkeypatch.setattr(cli, "exec_copilot", fake_exec)
    assert cli.launch_copilot(["suggest"]) == 0
    assert seen["args"] == ["suggest"]
    assert seen["env"]["CAR_PROVIDER_LOCK"] == "aws"
    assert seen["env"]["CAR_PROVIDER_LOCK_MODE"] == "prefer"


def test_launch_copilot_missing_key_prints_helper(monkeypatch):
    st = CarState(key_helper="car key --set")
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    assert cli.launch_copilot([]) == 1
    assert any("Run: car key --set" in str(args[0]) for args, _ in c.messages)


def test_launch_copilot_no_provider_lock(monkeypatch):
    st = CarState(selected_model="m", provider_lock=None)
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    monkeypatch.setattr(cli, "ensure_models_fresh", lambda state: None)
    monkeypatch.setattr(cli, "selected_model", lambda state: "model/x")
    monkeypatch.setattr(cli, "copilot_env", lambda *a: {})
    monkeypatch.setattr(cli, "exec_copilot", lambda args, env: 3)

    assert cli.launch_copilot([]) == 3


def test_print_models_and_format_price(monkeypatch):
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    rows = [ModelEntry("a/b", "a", 1.2, None, 3)]
    cli.print_models(rows, "now", "a")
    assert any("Cache refreshed:" in str(args[0]) for args, _ in c.messages)
    assert any("Provider lock active:" in str(args[0]) for args, _ in c.messages)

    assert cli.format_price(None) == "-"
    assert cli.format_price(1.23456) == "1.2346"


def test_print_models_without_optional_headers(monkeypatch):
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    rows = [ModelEntry("a/b", "a", None, None, None)]

    cli.print_models(rows, None, None)

    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Cache refreshed:" not in text_blob
    assert "Provider lock active:" not in text_blob


def test_ensure_models_fresh_refreshes_stale_cache(monkeypatch):
    st = CarState(openrouter_base_url="u")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([1], "old"))
    monkeypatch.setattr(cli, "cache_is_stale", lambda *_a, **_k: True)

    seen = {"called": 0}

    def fake_refresh(url):
        seen["called"] += 1
        assert url == "u"
        return []

    monkeypatch.setattr(cli, "refresh_models", fake_refresh)

    cli.ensure_models_fresh(st)
    assert seen["called"] == 1


def test_ensure_models_fresh_skips_when_fresh(monkeypatch):
    st = CarState(openrouter_base_url="u")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([1], "new"))
    monkeypatch.setattr(cli, "cache_is_stale", lambda *_a, **_k: False)

    seen = {"called": 0}
    monkeypatch.setattr(
        cli,
        "refresh_models",
        lambda _url: seen.update({"called": seen["called"] + 1}),
    )

    cli.ensure_models_fresh(st)
    assert seen["called"] == 0


def test_ensure_models_fresh_handles_refresh_error(monkeypatch):
    st = CarState(openrouter_base_url="u")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))

    def boom(_url):
        raise OpenRouterError("network")

    monkeypatch.setattr(cli, "refresh_models", boom)

    cli.ensure_models_fresh(st)
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Model cache refresh skipped:" in text_blob
