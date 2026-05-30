from __future__ import annotations

import argparse
import sys
from textwrap import dedent

from rich.console import Console
from rich.table import Table

from car.copilot import (
    check_copilot_extension,
    check_gh_auth,
    check_gh_installed,
    copilot_env,
    exec_copilot,
)
from car.openrouter import (
    OpenRouterError,
    cache_is_stale,
    filter_models,
    load_cached_models,
    refresh_models,
)
from car.paths import models_cache_file
from car.state import (
    CarState,
    load_state,
    resolve_openrouter_key,
    save_state,
    selected_model,
    state_path,
)
from car.tui import run_tui

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="car",
        add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=dedent(
            """
            car wraps Copilot CLI with OpenRouter model + provider controls.

            Default behavior:
            - Running `car` with no args launches Copilot in interactive mode.
            - Running an unrecognized command passes args through to Copilot.

            CLI mode examples:
            - `car suggest "write a safer bash script"`
            - `car explain "docker compose run --rm car"`

            car management examples:
            - `car doctor`                     # verify gh/auth/key/cache
            - `car model list`                 # show cached models/pricing
            - `car model refresh`              # force refresh pricing cache
            - `car --update`                   # re-run installer update flow

            Common workflows:
            - First run: `car doctor` -> `car model refresh` -> `car`
            - Daily use: run `car`, then use `suggest` or `explain` flows
            - Change model: `car model list` then `car model use <model_id>`
            - Lock provider: `car provider lock <provider>`

            Troubleshooting:
            - Missing auth: run `gh auth login`
            - Missing key: store in mattstash or set OPENROUTER_API_KEY
            - Empty cache: run `car model refresh`
            - Update wrapper/tools: run `car --update`
            """
        ).strip(),
    )
    sub = parser.add_subparsers(dest="command")

    model = sub.add_parser("model", help="Model management")
    model_sub = model.add_subparsers(dest="action")

    model_sub.add_parser("list", help="List cached models")
    model_sub.add_parser("ls", help="Alias for list")
    model_sub.add_parser("refresh", help="Refresh model cache from OpenRouter")
    model_sub.add_parser("current", help="Show current model")

    use = model_sub.add_parser("use", help="Set selected model")
    use.add_argument("model_id")

    provider = sub.add_parser("provider", help="Provider lock commands")
    provider_sub = provider.add_subparsers(dest="action")
    lock = provider_sub.add_parser(
        "lock",
        help="Lock model selection to provider",
    )
    lock.add_argument("provider")
    mode = provider_sub.add_parser("mode", help="Set provider lock mode")
    mode.add_argument("value", choices=["strict", "prefer"])
    provider_sub.add_parser("unlock", help="Clear provider lock")
    provider_sub.add_parser("current", help="Show current provider lock")

    sub.add_parser("env", help="Show resolved provider environment")
    sub.add_parser("doctor", help="Check installation and auth")
    sub.add_parser("tui", help="Open Textual model selector")
    sub.add_parser("config", help="Print state file path")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()

    if argv and argv[0] in {"-h", "--help", "help"}:
        parser.print_help()
        return 0

    if not argv:
        return launch_copilot([])

    if argv[0] in {"model", "provider", "env", "doctor", "tui", "config"}:
        args = parser.parse_args(argv)
        return dispatch_subcommand(args)

    return launch_copilot(argv)


def dispatch_subcommand(args: argparse.Namespace) -> int:
    state = load_state()

    if args.command == "model":
        return handle_model(state, args)
    if args.command == "provider":
        return handle_provider(state, args)
    if args.command == "env":
        return handle_env(state)
    if args.command == "doctor":
        return handle_doctor(state)
    if args.command == "tui":
        return handle_tui(state)
    if args.command == "config":
        return handle_config()
    return 1


def handle_model(state: CarState, args: argparse.Namespace) -> int:
    action = args.action or "list"

    if action in {"list", "ls"}:
        rows, refreshed_at = load_cached_models()
        if not rows:
            console.print("Model cache missing. Refreshing now...")
            try:
                rows = refresh_models(state.openrouter_base_url)
                refreshed_at = "just now"
            except OpenRouterError as exc:
                console.print(f"Refresh failed: {exc}")
                return 1

        rows = filter_models(rows, state.provider_lock)
        print_models(rows, refreshed_at, state.provider_lock)
        return 0

    if action == "refresh":
        try:
            rows = refresh_models(state.openrouter_base_url)
        except OpenRouterError as exc:
            console.print(f"Refresh failed: {exc}")
            return 1

        console.print(
            f"Refreshed {len(rows)} models into {models_cache_file()}"
        )
        return 0

    if action == "use":
        state.selected_model = args.model_id
        save_state(state)
        console.print(f"Selected model: {args.model_id}")
        return 0

    if action == "current":
        console.print(selected_model(state))
        return 0

    console.print("Unknown model action")
    return 1


def handle_provider(state: CarState, args: argparse.Namespace) -> int:
    action = args.action or "current"

    if action == "lock":
        state.provider_lock = args.provider
        save_state(state)
        console.print(f"Provider lock set to: {state.provider_lock}")
        return 0

    if action == "mode":
        state.provider_lock_mode = args.value
        save_state(state)
        console.print(f"Provider lock mode: {state.provider_lock_mode}")
        return 0

    if action == "unlock":
        state.provider_lock = None
        save_state(state)
        console.print("Provider lock cleared")
        return 0

    if action == "current":
        lock = state.provider_lock or "<none>"
        console.print(f"provider_lock={lock}")
        console.print(f"provider_lock_mode={state.provider_lock_mode}")
        return 0

    return 1


def handle_env(state: CarState) -> int:
    key = resolve_openrouter_key(state)
    model = selected_model(state)

    console.print(f"COPILOT_PROVIDER_BASE_URL={state.openrouter_base_url}")
    console.print(f"COPILOT_MODEL={model}")
    console.print(f"CAR_PROVIDER_LOCK={state.provider_lock or ''}")
    if key:
        console.print("COPILOT_PROVIDER_API_KEY=<set>")
    else:
        console.print("COPILOT_PROVIDER_API_KEY=<unset>")
        if state.key_helper:
            console.print(f"Hint: run {state.key_helper}")
    return 0


def handle_doctor(state: CarState) -> int:
    checks = [
        check_gh_installed(),
        check_copilot_extension(),
        check_gh_auth(),
    ]

    key = resolve_openrouter_key(state)
    checks.append(
        type("_Doctor", (), {
            "name": "openrouter-key",
            "ok": bool(key),
            "detail": (
                "Key resolved"
                if key
                else "No key found in env or mattstash"
            ),
        })()
    )

    rows, _ = load_cached_models()
    checks.append(
        type("_Doctor", (), {
            "name": "model-cache",
            "ok": bool(rows),
            "detail": (
                f"{len(rows)} cached models"
                if rows
                else "Cache empty; run car model refresh"
            ),
        })()
    )

    ok = True
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        color = "green" if check.ok else "red"
        console.print(
            f"[{color}]{status}[/{color}] {check.name}: {check.detail}"
        )
        ok = ok and bool(check.ok)

    return 0 if ok else 1


def handle_tui(state: CarState) -> int:
    rows, _ = load_cached_models()
    if not rows:
        console.print("Model cache missing. Refreshing now...")
        try:
            rows = refresh_models(state.openrouter_base_url)
        except OpenRouterError as exc:
            console.print(f"Refresh failed: {exc}")
            return 1

    outcome = run_tui(rows, selected_model(state), state.provider_lock)
    if not outcome:
        return 0

    model_id, provider_lock = outcome
    state.selected_model = model_id
    state.provider_lock = provider_lock
    save_state(state)

    console.print(f"Selected model: {model_id}")
    console.print(f"Provider lock: {provider_lock or '<none>'}")
    return 0


def handle_config() -> int:
    console.print(str(state_path()))
    return 0


def launch_copilot(copilot_args: list[str]) -> int:
    state = load_state()
    key = resolve_openrouter_key(state)
    if not key:
        console.print("OpenRouter key not found.", style="red")
        if state.key_helper:
            console.print(f"Run: {state.key_helper}")
        return 1

    ensure_models_fresh(state)

    model = selected_model(state)
    env = copilot_env(state.openrouter_base_url, key, model)

    # Provider lock is a local policy for model filtering and state.
    # We surface it here for future integrations that can pass routing hints.
    if state.provider_lock:
        env["CAR_PROVIDER_LOCK"] = state.provider_lock
        env["CAR_PROVIDER_LOCK_MODE"] = state.provider_lock_mode

    return exec_copilot(copilot_args, env)


def ensure_models_fresh(state: CarState, max_age_hours: int = 24) -> None:
    rows, refreshed_at = load_cached_models()
    if rows and not cache_is_stale(refreshed_at, max_age_hours=max_age_hours):
        return

    reason = "missing" if not rows else f"older than {max_age_hours}h"
    console.print(f"Model cache is {reason}. Refreshing...")

    try:
        refresh_models(state.openrouter_base_url)
    except OpenRouterError as exc:
        console.print(
            f"Model cache refresh skipped: {exc}",
            style="yellow",
        )


def print_models(
    rows,
    refreshed_at: str | None,
    provider_lock: str | None,
) -> None:
    table = Table(title="OpenRouter Models")
    table.add_column("Provider", style="cyan")
    table.add_column("Model")
    table.add_column("Prompt/$1M", justify="right")
    table.add_column("Complete/$1M", justify="right")
    table.add_column("Context", justify="right")

    for row in rows:
        table.add_row(
            row.provider,
            row.model_id,
            format_price(row.prompt_per_million),
            format_price(row.completion_per_million),
            str(row.context_length or "-"),
        )

    if refreshed_at:
        console.print(f"Cache refreshed: {refreshed_at}")
    if provider_lock:
        console.print(f"Provider lock active: {provider_lock}")
    console.print(table)


def format_price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"
