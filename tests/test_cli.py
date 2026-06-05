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


def test_build_parser_parses_model_set_alias():
    parser = cli.build_parser()
    ns = parser.parse_args(["model", "set", "x/y"])
    assert ns.command == "model"
    assert ns.action == "set"
    assert ns.model_id == "x/y"


def test_build_parser_parses_model_list_provider_filter():
    parser = cli.build_parser()
    ns = parser.parse_args(["model", "list", "--provider", "openai,google"])
    assert ns.command == "model"
    assert ns.action == "list"
    assert ns.provider == "openai,google"


def test_build_parser_parses_key_verify():
    parser = cli.build_parser()
    ns = parser.parse_args(["key", "verify"])
    assert ns.command == "key"
    assert ns.action == "verify"


def test_build_parser_parses_key_set():
    parser = cli.build_parser()
    ns = parser.parse_args(["key", "set", "--value", "tok", "--key-name", "name"])
    assert ns.command == "key"
    assert ns.action == "set"
    assert ns.value == "tok"
    assert ns.key_name == "name"


def test_main_routes_no_args(monkeypatch):
    monkeypatch.setattr(cli, "launch_harness", lambda args: 7)
    assert cli.main([]) == 7


def test_main_routes_subcommand(monkeypatch):
    monkeypatch.setattr(cli, "dispatch_subcommand", lambda args: 8)
    assert cli.main(["env"]) == 8


def test_main_routes_cli_flag_to_gh_backend(monkeypatch):
    received = {"args": None, "backend": None}

    def fake_launch(args, backend=None):
        received["args"] = args
        received["backend"] = backend
        return 10

    monkeypatch.setattr(cli, "launch_copilot", fake_launch)
    assert cli.main(["--cli", "suggest", "hello"]) == 10
    assert received["args"] == ["suggest", "hello"]
    assert received["backend"] == "gh"


def test_main_routes_help_to_local_parser(monkeypatch):
    seen = {"help": 0, "launch": 0}

    class _Parser:
        def print_help(self):
            seen["help"] += 1

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())
    monkeypatch.setattr(
        cli,
        "launch_harness",
        lambda args: seen.update({"launch": seen["launch"] + 1}) or 9,
    )

    assert cli.main(["--help"]) == 0
    assert seen["help"] == 1
    assert seen["launch"] == 0


def test_main_routes_help_alias_to_local_parser(monkeypatch):
    seen = {"help": 0}

    class _Parser:
        def print_help(self):
            seen["help"] += 1

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())
    assert cli.main(["help"]) == 0
    assert seen["help"] == 1


def test_main_routes_passthrough(monkeypatch):
    received = {"args": None}

    def fake_launch(args):
        received["args"] = args
        return 9

    monkeypatch.setattr(cli, "launch_harness", fake_launch)
    assert cli.main(["suggest", "hello"]) == 9
    assert received["args"] == ["suggest", "hello"]


def test_main_routes_model_without_action_to_model_help(monkeypatch):
    seen = {"parsed": None, "dispatch": 0, "launch": 0}

    class _Parser:
        def parse_args(self, args):
            seen["parsed"] = args
            raise SystemExit(0)

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())
    monkeypatch.setattr(
        cli,
        "dispatch_subcommand",
        lambda _args: seen.update({"dispatch": seen["dispatch"] + 1}) or 1,
    )
    monkeypatch.setattr(
        cli,
        "launch_copilot",
        lambda _args: seen.update({"launch": seen["launch"] + 1}) or 1,
    )

    assert cli.main(["model"]) == 0
    assert seen["parsed"] == ["model", "--help"]
    assert seen["dispatch"] == 0
    assert seen["launch"] == 0


def test_dispatch_subcommand_all_branches(monkeypatch):
    st = CarState()
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "handle_model", lambda state, args: 1)
    monkeypatch.setattr(cli, "handle_provider", lambda state, args: 2)
    monkeypatch.setattr(cli, "handle_key", lambda state, args: 3)
    monkeypatch.setattr(cli, "handle_env", lambda state: 4)
    monkeypatch.setattr(cli, "handle_doctor", lambda state: 5)
    monkeypatch.setattr(cli, "handle_tui", lambda state: 6)
    monkeypatch.setattr(cli, "handle_config", lambda: 7)
    monkeypatch.setattr(cli, "handle_harness", lambda state, args: 8)

    assert cli.dispatch_subcommand(_args(command="model")) == 1
    assert cli.dispatch_subcommand(_args(command="provider")) == 2
    assert cli.dispatch_subcommand(_args(command="key")) == 3
    assert cli.dispatch_subcommand(_args(command="env")) == 4
    assert cli.dispatch_subcommand(_args(command="doctor")) == 5
    assert cli.dispatch_subcommand(_args(command="tui")) == 6
    assert cli.dispatch_subcommand(_args(command="config")) == 7
    assert cli.dispatch_subcommand(_args(command="harness")) == 8
    assert cli.dispatch_subcommand(_args(command="other")) == 1


def test_main_routes_key_without_action_to_help(monkeypatch):
    seen = {"parsed": None}

    class _Parser:
        def parse_args(self, args):
            seen["parsed"] = args
            raise SystemExit(0)

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())
    assert cli.main(["key"]) == 0
    assert seen["parsed"] == ["key", "--help"]


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


def test_handle_model_list_with_provider_arg(monkeypatch):
    st = CarState(provider_lock="openai")
    rows = [
        ModelEntry("openai/gpt", "openai", 1.0, 2.0, 3),
        ModelEntry("google/gemini", "google", 1.0, 2.0, 3),
        ModelEntry("anthropic/claude", "anthropic", 1.0, 2.0, 3),
    ]

    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))
    monkeypatch.setattr(cli, "filter_models", lambda r, p: r)

    seen = {"rows": None, "provider_lock": None}

    def fake_print_models(rows_arg, refreshed_at, provider_lock):
        seen["rows"] = rows_arg
        seen["provider_lock"] = provider_lock

    monkeypatch.setattr(cli, "print_models", fake_print_models)

    assert cli.handle_model(st, _args(action="list", provider="openai,google")) == 0
    assert [row.provider for row in seen["rows"]] == ["openai", "google"]
    assert seen["provider_lock"] is None


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
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))

    saved = {"called": False}

    def fake_save(state):
        saved["called"] = True

    monkeypatch.setattr(cli, "save_state", fake_save)

    assert cli.handle_model(st, _args(action="use", model_id="a/b")) == 0
    assert saved["called"] is True
    assert st.selected_model == "a/b"

    assert cli.handle_model(st, _args(action="set", model_id="c/d")) == 0
    assert st.selected_model == "c/d"

    assert cli.handle_model(st, _args(action="current")) == 0
    assert cli.handle_model(st, _args(action="nope")) == 1


def test_handle_model_favorites_actions(monkeypatch):
    st = CarState(favorite_models=["a/b"])
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "save_state", lambda _state: None)

    assert cli.handle_model(st, _args(action="favorites")) == 0
    assert cli.handle_model(st, _args(action="favorite-add", model_id="x/y")) == 0
    assert "x/y" in st.favorite_models
    before = list(st.favorite_models)
    assert cli.handle_model(st, _args(action="favorite-add", model_id="x/y")) == 0
    assert st.favorite_models == before

    assert cli.handle_model(st, _args(action="favorite-remove", model_id="a/b")) == 0
    assert "a/b" not in st.favorite_models

    assert cli.handle_model(st, _args(action="favorite-use", model_id="x/y")) == 0
    assert st.selected_model == "x/y"
    assert cli.handle_model(st, _args(action="favorite-use", model_id="missing")) == 1


def test_handle_model_favorites_empty(monkeypatch):
    st = CarState(favorite_models=[])
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    assert cli.handle_model(st, _args(action="favorites")) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "No favorite models set" in text_blob


def test_handle_provider_branches(monkeypatch):
    st = CarState()
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "save_state", lambda state: None)

    assert cli.handle_provider(st, _args(action="lock", provider="aws-bedrock")) == 0
    assert st.provider_lock == "aws-bedrock"

    assert cli.handle_provider(st, _args(action="mode", value="prefer")) == 0
    assert st.provider_lock_mode == "prefer"

    assert cli.handle_provider(st, _args(action="route", value="provider")) == 0
    assert st.route_mode == "provider"

    assert cli.handle_provider(st, _args(action="unlock")) == 0
    assert st.provider_lock is None

    assert cli.handle_provider(st, _args(action="current")) == 0
    assert cli.handle_provider(st, _args(action="unknown")) == 1


def test_handle_provider_list_from_cache(monkeypatch):
    st = CarState(openrouter_base_url="u")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(
        cli,
        "load_cached_models",
        lambda: ([
            ModelEntry("openai/gpt", "openai", None, None, None),
            ModelEntry("google/gemini", "google", None, None, None),
        ], "now"),
    )

    assert cli.handle_provider(st, _args(action="list")) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "openai" in text_blob
    assert "google" in text_blob


def test_handle_provider_list_refresh_paths(monkeypatch):
    st = CarState(openrouter_base_url="u")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))
    monkeypatch.setattr(
        cli,
        "refresh_models",
        lambda _url: [ModelEntry("a/b", "a", None, None, None)],
    )

    assert cli.handle_provider(st, _args(action="ls")) == 0

    def boom(_url):
        raise OpenRouterError("bad")

    monkeypatch.setattr(cli, "refresh_models", boom)
    assert cli.handle_provider(st, _args(action="list")) == 1


def test_handle_env(monkeypatch):
    st = CarState(
        selected_model="a/b", provider_lock="aws", key_helper="helper",
    )
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    assert cli.handle_env(st) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "CAR_HARNESS=copilot" in text_blob

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


def test_handle_key_paths(monkeypatch):
    st = CarState(openrouter_base_url="u", key_helper="car key --set")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "resolve_openrouter_key_with_source", lambda _state: (None, None))
    assert cli.handle_key(st, _args(action="verify")) == 1

    monkeypatch.setattr(cli, "resolve_openrouter_key_with_source", lambda _state: ("tok", "mattstash:openrouter_api_key"))
    monkeypatch.setattr(cli, "verify_api_key", lambda _url, _key: {"data": {"label": "main", "usage": 12}})
    assert cli.handle_key(st, _args(action="verify")) == 0

    def boom(_url, _key):
        raise OpenRouterError("bad")

    monkeypatch.setattr(cli, "verify_api_key", boom)
    assert cli.handle_key(st, _args(action="verify")) == 1
    assert cli.handle_key(st, _args(action="unknown")) == 1


def test_handle_key_no_helper_and_optional_fields(monkeypatch):
    st = CarState(openrouter_base_url="u", key_helper="")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    # Covers missing-key path without helper message.
    monkeypatch.setattr(cli, "resolve_openrouter_key_with_source", lambda _state: (None, None))
    assert cli.handle_key(st, _args(action="verify")) == 1
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Run:" not in text_blob

    # Covers success path where label/usage are absent.
    monkeypatch.setattr(cli, "resolve_openrouter_key_with_source", lambda _state: ("tok", "OPENROUTER_API_KEY"))
    monkeypatch.setattr(cli, "verify_api_key", lambda _url, _key: {"data": {}})
    assert cli.handle_key(st, _args(action="verify")) == 0


def test_handle_key_rejected_env_source_hint(monkeypatch):
    st = CarState(openrouter_base_url="u", key_helper="")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(
        cli,
        "resolve_openrouter_key_with_source",
        lambda _state: ("tok", "OPENROUTER_API_KEY"),
    )

    def boom(_url, _key):
        raise OpenRouterError("OpenRouter API key rejected (HTTP 401)")

    monkeypatch.setattr(cli, "verify_api_key", boom)
    assert cli.handle_key(st, _args(action="verify")) == 1
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Resolved key source: OPENROUTER_API_KEY" in text_blob
    assert "environment variable is overriding mattstash" in text_blob


def test_handle_key_without_source_branches(monkeypatch):
    st = CarState(openrouter_base_url="u", key_helper="")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    # Failure path with no source should not print source line.
    monkeypatch.setattr(
        cli,
        "resolve_openrouter_key_with_source",
        lambda _state: ("tok", None),
    )

    def boom(_url, _key):
        raise OpenRouterError("network down")

    monkeypatch.setattr(cli, "verify_api_key", boom)
    assert cli.handle_key(st, _args(action="verify")) == 1
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Resolved key source:" not in text_blob

    # Success path with no source should also skip source line.
    c.messages.clear()
    monkeypatch.setattr(cli, "verify_api_key", lambda _url, _key: {"data": {"label": "main"}})
    assert cli.handle_key(st, _args(action="verify")) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Resolved key source:" not in text_blob


def test_handle_key_set_paths(monkeypatch):
    st = CarState(openrouter_base_url="u", key_name="openrouter_api_key")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    seen = {"saved": 0, "value": None, "key_name": None}

    def fake_store(_state, value, key_name=None):
        seen["value"] = value
        seen["key_name"] = key_name
        return key_name or "openrouter_api_key"

    monkeypatch.setattr(cli, "store_openrouter_key", fake_store)
    monkeypatch.setattr(
        cli,
        "save_state",
        lambda _state: seen.update({"saved": seen["saved"] + 1}),
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: "prompt-token")

    assert cli.handle_key(st, _args(action="set", value="", key_name="")) == 0
    assert seen["value"] == "prompt-token"

    assert cli.handle_key(st, _args(action="set", value="arg-token", key_name="my_key")) == 0
    assert seen["value"] == "arg-token"
    assert seen["key_name"] == "my_key"
    assert st.key_name == "my_key"
    assert seen["saved"] == 1


def test_handle_key_set_failures(monkeypatch):
    st = CarState()
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: "")
    assert cli.handle_key(st, _args(action="set", value="", key_name="")) == 1

    def boom(*_args, **_kwargs):
        raise RuntimeError("bad")

    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: "tok")
    monkeypatch.setattr(cli, "store_openrouter_key", boom)
    assert cli.handle_key(st, _args(action="set", value="", key_name="")) == 1


def test_handle_key_set_cancelled(monkeypatch):
    st = CarState()
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    def cancelled(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.getpass, "getpass", cancelled)
    assert cli.handle_key(st, _args(action="set", value="", key_name="")) == 1


def test_handle_doctor_success_and_failure(monkeypatch):
    st = CarState()
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "detect_available_harnesses", lambda: ["copilot"])
    monkeypatch.setattr(cli, "check_gh_installed", lambda: _Check("gh", True, "ok"))
    monkeypatch.setattr(cli, "check_copilot_extension", lambda: _Check("ext", True, "ok"))
    monkeypatch.setattr(cli, "check_gh_auth", lambda: _Check("auth", True, "ok"))
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "k")
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([1], "now"))
    monkeypatch.setattr(cli, "resolve_model_token_limits", lambda _model: (123, 45))
    assert cli.handle_doctor(st) == 0

    monkeypatch.setattr(cli, "detect_available_harnesses", lambda: [])
    monkeypatch.setattr(cli, "check_gh_installed", lambda: _Check("gh", False, "bad"))
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([], None))
    monkeypatch.setattr(cli, "resolve_model_token_limits", lambda _model: (None, None))
    assert cli.handle_doctor(st) == 1


def test_handle_tui_paths(monkeypatch):
    st = CarState(openrouter_base_url="u", provider_lock="aws", route_mode="model")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    rows = [ModelEntry("a/b", "a", None, None, None)]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))
    monkeypatch.setattr(cli, "run_tui", lambda *a: None)
    assert cli.handle_tui(st) == 0

    monkeypatch.setattr(
        cli, "run_tui",
        lambda *a: ("x/y", "openai", "provider", ["x/y"], "copilot"),
    )
    saved = {"called": False}
    monkeypatch.setattr(
        cli,
        "save_state",
        lambda state: saved.update({"called": True}),
    )
    monkeypatch.setattr(cli, "launch_copilot", lambda args: 0)
    assert cli.handle_tui(st) == 0
    assert st.selected_model == "x/y"
    assert st.provider_lock == "openai"
    assert st.route_mode == "provider"
    assert st.favorite_models == ["x/y"]
    assert st.harness == "copilot"
    assert saved["called"] is True

    seen = {"args": None}
    monkeypatch.setattr(cli, "launch_copilot", lambda args: seen.update({"args": args}) or 0)
    assert cli.handle_tui(st) == 0
    assert seen["args"] == []


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
    monkeypatch.setattr(cli, "launch_copilot", lambda args: 0)
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
    st = CarState(
        selected_model="m", provider_lock="aws",
        provider_lock_mode="prefer", route_mode="provider",
    )
    monkeypatch.setattr(cli, "load_state", lambda: st)

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)
    assert cli.launch_copilot([]) == 1

    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    monkeypatch.setattr(cli, "ensure_models_fresh", lambda state: None)
    monkeypatch.setattr(cli, "selected_model", lambda state: "model/x")
    monkeypatch.setattr(cli, "build_harness_env", lambda *a: {})
    monkeypatch.setattr(
        cli, "resolve_model_token_limits", lambda _model: (1234, 456),
    )

    seen = {"args": None, "env": None}

    def fake_exec(harness, args, env, backend=None):
        seen["args"] = args
        seen["env"] = env
        seen["backend"] = backend
        return 0

    monkeypatch.setattr(cli, "exec_harness", fake_exec)
    assert cli.launch_copilot(["suggest"]) == 0
    assert seen["args"] == ["suggest"]
    assert seen["env"]["CAR_PROVIDER_LOCK"] == "aws"
    assert seen["env"]["CAR_PROVIDER_LOCK_MODE"] == "prefer"
    assert seen["env"]["CAR_ROUTE_MODE"] == "provider"
    assert seen["env"]["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] == "1234"
    assert seen["env"]["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] == "456"


def test_launch_copilot_missing_key_prints_helper(monkeypatch):
    st = CarState(key_helper="car key --set")
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    assert cli.launch_copilot([]) == 1
    assert any("Run: car key --set" in str(args[0]) for args, _ in c.messages)


def test_launch_harness_claude_skips_token_limit_env(monkeypatch):
    st = CarState(selected_model="m", provider_lock=None, harness="claude")
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    monkeypatch.setattr(cli, "ensure_models_fresh", lambda state: None)
    monkeypatch.setattr(cli, "selected_model", lambda state: "model/x")
    monkeypatch.setattr(cli, "build_harness_env", lambda *a: {})
    monkeypatch.setattr(
        cli, "resolve_model_token_limits", lambda _model: (9999, 1234),
    )

    seen = {"env": None}

    def fake_exec(harness, args, env, backend=None):
        seen["env"] = env
        return 0

    monkeypatch.setattr(cli, "exec_harness", fake_exec)
    assert cli.launch_harness([]) == 0
    assert "COPILOT_PROVIDER_MAX_PROMPT_TOKENS" not in seen["env"]
    assert "COPILOT_PROVIDER_MAX_OUTPUT_TOKENS" not in seen["env"]


def test_launch_copilot_no_provider_lock(monkeypatch):
    st = CarState(selected_model="m", provider_lock=None)
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    monkeypatch.setattr(cli, "ensure_models_fresh", lambda state: None)
    monkeypatch.setattr(cli, "selected_model", lambda state: "model/x")
    monkeypatch.setattr(cli, "build_harness_env", lambda *a: {})
    monkeypatch.setattr(cli, "resolve_model_token_limits", lambda _model: (None, None))
    monkeypatch.setattr(
        cli, "exec_harness",
        lambda h, a, e, backend=None: 3,

    )

    assert cli.launch_copilot([]) == 3


def test_launch_copilot_passes_backend(monkeypatch):
    st = CarState(selected_model="m", provider_lock=None)
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    monkeypatch.setattr(cli, "ensure_models_fresh", lambda state: None)
    monkeypatch.setattr(cli, "selected_model", lambda state: "model/x")
    monkeypatch.setattr(cli, "build_harness_env", lambda *a: {})
    monkeypatch.setattr(cli, "resolve_model_token_limits", lambda _model: (None, None))

    seen = {"backend": None}

    def fake_exec(harness, args, env, backend=None):
        seen["backend"] = backend
        return 0

    monkeypatch.setattr(cli, "exec_harness", fake_exec)
    assert cli.launch_copilot([], backend="gh") == 0
    assert seen["backend"] == "gh"


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


def test_filter_models_by_provider_arg_helper():
    rows = [
        ModelEntry("openai/gpt", "openai", None, None, None),
        ModelEntry("google/gemini", "google", None, None, None),
    ]

    assert cli.filter_models_by_provider_arg(rows, "") == rows
    filtered = cli.filter_models_by_provider_arg(rows, "OPENAI, google")
    assert [row.provider for row in filtered] == ["openai", "google"]


def test_normalize_model_selection_short_id_warns_and_resolves(monkeypatch):
    rows = [
        ModelEntry("deepseek/deepseek-v4-pro", "deepseek", None, None, 128000),
    ]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    resolved = cli.normalize_model_selection("deepseek-v4-pro")
    assert resolved == "deepseek/deepseek-v4-pro"

    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "imprecise" in text_blob
    assert "deepseek/deepseek-v4-pro" in text_blob


def test_normalize_model_selection_typo_suggests(monkeypatch):
    rows = [
        ModelEntry("deepseek/deepseek-v4-pro", "deepseek", None, None, 128000),
    ]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    resolved = cli.normalize_model_selection("deepseek/depseek-v4-pro")
    assert resolved == "deepseek/depseek-v4-pro"

    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "Did you mean:" in text_blob
    assert "deepseek/deepseek-v4-pro" in text_blob


def test_normalize_model_selection_exact_and_empty_cases(monkeypatch):
    rows = [
        ModelEntry("openai/gpt-4o-mini", "openai", None, None, 128000),
    ]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))

    assert cli.normalize_model_selection("OPENAI/GPT-4O-MINI") == "openai/gpt-4o-mini"
    assert cli.normalize_model_selection("") == ""


def test_normalize_model_selection_without_suggestions(monkeypatch):
    rows = [
        ModelEntry("openai/gpt-4o-mini", "openai", None, None, 128000),
    ]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))

    c = _Console()
    monkeypatch.setattr(cli, "console", c)

    resolved = cli.normalize_model_selection("totally-unknown-model")
    assert resolved == "totally-unknown-model"
    assert c.messages == []


def test_suggest_model_corrections_helper():
    rows = [
        ModelEntry("deepseek/deepseek-v4-pro", "deepseek", None, None, None),
        ModelEntry("openai/gpt-4o-mini", "openai", None, None, None),
    ]
    suggestions = cli.suggest_model_corrections("depseek-v4-pro", rows)
    assert suggestions[0] == "deepseek/deepseek-v4-pro"
    assert cli.suggest_model_corrections("", rows) == []


def test_suggest_model_corrections_additional_branches():
    rows = [
        ModelEntry("deepseek/deepseek-v4-pro", "deepseek", None, None, None),
        ModelEntry("deepseek/deepseek-v4-pro", "deepseek", None, None, None),
        ModelEntry("deepseek/deepseek-v3", "deepseek", None, None, None),
        ModelEntry("openai/gpt-4o-mini", "openai", None, None, None),
    ]

    # Hits substring boost path and limit break path.
    limited = cli.suggest_model_corrections("deepseek", rows, limit=1)
    assert len(limited) == 1
    assert limited[0].startswith("deepseek/")

    # Hits duplicate-skip path when model is already present in ordered.
    deduped = cli.suggest_model_corrections("deepseek", rows, limit=5)
    assert deduped.count("deepseek/deepseek-v4-pro") == 1

    # Hits non-empty needle with no scored matches.
    assert cli.suggest_model_corrections("zzzzzzzz", rows) == []


def test_resolve_model_token_limits(monkeypatch):
    rows = [
        ModelEntry(
            "openai/gpt-4o-mini",
            "openai",
            None,
            None,
            128000,
            120000,
            8000,
        )
    ]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))

    assert cli.resolve_model_token_limits("openai/gpt-4o-mini") == (120000, 8000)
    assert cli.resolve_model_token_limits("gpt-4o-mini") == (120000, 8000)
    assert cli.resolve_model_token_limits("missing/model") == (None, None)


def test_resolve_model_token_limits_ambiguous_short_id(monkeypatch):
    rows = [
        ModelEntry("openai/same", "openai", None, None, 10, 8, 2),
        ModelEntry("anthropic/same", "anthropic", None, None, 12, 10, 2),
    ]
    monkeypatch.setattr(cli, "load_cached_models", lambda: (rows, "now"))

    assert cli.resolve_model_token_limits("same") == (None, None)


# ── Harness subcommand tests ─────────────────────────────────────────────────


def test_build_parser_parses_harness_list():
    parser = cli.build_parser()
    ns = parser.parse_args(["harness", "list"])
    assert ns.command == "harness"
    assert ns.action == "list"


def test_build_parser_parses_harness_use():
    parser = cli.build_parser()
    ns = parser.parse_args(["harness", "use", "claude"])
    assert ns.command == "harness"
    assert ns.action == "use"
    assert ns.name == "claude"


def test_build_parser_harness_use_invalid_choice():
    parser = cli.build_parser()
    import pytest
    with pytest.raises(SystemExit):
        parser.parse_args(["harness", "use", "invalid"])


def test_main_routes_harness_subcommand(monkeypatch):
    monkeypatch.setattr(
        cli, "dispatch_subcommand", lambda args: 8,
    )
    assert cli.main(["harness", "list"]) == 8


def test_dispatch_harness(monkeypatch):
    st = CarState()
    monkeypatch.setattr(cli, "load_state", lambda: st)
    monkeypatch.setattr(cli, "handle_harness", lambda state, args: 5)
    assert cli.dispatch_subcommand(_args(command="harness")) == 5


def test_handle_harness_list_empty(monkeypatch):
    st = CarState()
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "detect_available_harnesses", lambda: [])
    assert cli.handle_harness(st, _args(action="list")) == 1


def test_handle_harness_list_with_available(monkeypatch):
    st = CarState(harness="copilot")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(
        cli, "detect_available_harnesses",
        lambda: ["copilot", "claude"],
    )
    assert cli.handle_harness(st, _args(action="ls")) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "copilot" in text_blob
    assert "claude" in text_blob


def test_handle_harness_use_success(monkeypatch):
    st = CarState(harness="copilot")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(
        cli, "detect_available_harnesses",
        lambda: ["copilot", "claude"],
    )
    monkeypatch.setattr(cli, "save_state", lambda _state: None)
    assert cli.handle_harness(st, _args(action="use", name="claude")) == 0
    assert st.harness == "claude"


def test_handle_harness_use_not_installed(monkeypatch):
    st = CarState(harness="copilot")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "detect_available_harnesses", lambda: ["copilot"])
    assert cli.handle_harness(st, _args(action="use", name="claude")) == 1


def test_handle_harness_current(monkeypatch):
    st = CarState(harness="claude")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(
        cli, "detect_available_harnesses",
        lambda: ["copilot", "claude"],
    )
    assert cli.handle_harness(st, _args(action="current")) == 0


def test_handle_harness_unknown(monkeypatch):
    st = CarState()
    assert cli.handle_harness(st, _args(action="unknown")) == 1


def test_handle_harness_pick_empty(monkeypatch):
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "detect_available_harnesses", lambda: [])
    assert cli.handle_harness_pick() == 1


def test_handle_harness_pick_single(monkeypatch):
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(
        cli, "detect_available_harnesses", lambda: ["copilot"],
    )
    monkeypatch.setattr(cli, "load_state", lambda: CarState())
    monkeypatch.setattr(cli, "save_state", lambda _state: None)
    assert cli.handle_harness_pick() == 0


def test_handle_harness_set_and_launch(monkeypatch):
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "load_state", lambda: CarState())
    monkeypatch.setattr(cli, "save_state", lambda _state: None)

    assert cli.handle_harness_set_and_launch("invalid", []) == 1
    assert cli.handle_harness_set_and_launch("claude", []) == 0

    monkeypatch.setattr(
        cli, "launch_harness", lambda args: 42,
    )
    assert cli.handle_harness_set_and_launch("claude", ["chat"]) == 42


def test_handle_env_shows_harness_info(monkeypatch):
    st = CarState(harness="claude", selected_model="a/b")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "token")
    assert cli.handle_env(st) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "CAR_HARNESS=claude" in text_blob
    assert "ANTHROPIC_BASE_URL" in text_blob
    assert "ANTHROPIC_API_KEY=<set>" in text_blob


def test_handle_env_copilot_shows_copilot_vars(monkeypatch):
    st = CarState(harness="copilot", selected_model="a/b")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: None)
    assert cli.handle_env(st) == 0
    text_blob = "\n".join(str(args[0]) for args, _ in c.messages if args)
    assert "CAR_HARNESS=copilot" in text_blob
    assert "COPILOT_PROVIDER_BASE_URL" in text_blob
    assert "COPILOT_PROVIDER_API_KEY=<unset>" in text_blob


def test_handle_doctor_claude_harness(monkeypatch):
    st = CarState(harness="claude")
    c = _Console()
    monkeypatch.setattr(cli, "console", c)
    monkeypatch.setattr(
        cli, "detect_available_harnesses", lambda: ["claude"],
    )
    monkeypatch.setattr(
        cli, "check_claude_installed",
        lambda: _Check("claude", True, "ok"),
    )
    monkeypatch.setattr(cli, "resolve_openrouter_key", lambda state: "k")
    monkeypatch.setattr(cli, "load_cached_models", lambda: ([1], "now"))
    monkeypatch.setattr(
        cli, "resolve_model_token_limits", lambda _model: (123, 45),
    )
    assert cli.handle_doctor(st) == 0


def test_main_harness_flag_no_arg(monkeypatch):
    monkeypatch.setattr(cli, "handle_harness_pick", lambda: 5)
    assert cli.main(["--harness"]) == 5


def test_main_harness_flag_with_name(monkeypatch):
    monkeypatch.setattr(cli, "handle_harness_set_and_launch", lambda n, r: 6)
    assert cli.main(["--harness", "claude"]) == 6
