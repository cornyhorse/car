from __future__ import annotations

import argparse
import difflib
import getpass
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from rich.console import Console
from rich.table import Table

from car.copilot import (
    check_copilot_extension,
    check_gh_auth,
    check_gh_installed,
)
from car.harness import (
    DoctorResult,
    HarnessName,
    build_harness_env,
    check_claude_installed,
    detect_available_harnesses,
    exec_harness,
    harness_display_name,
)
from car.openrouter import (
    OpenRouterError,
    cache_is_stale,
    filter_models,
    load_cached_models,
    refresh_models,
    verify_api_key,
)
from car.paths import models_cache_file
from car.state import (
    CarState,
    load_state,
    resolve_openrouter_key,
    resolve_openrouter_key_with_source,
    save_state,
    selected_model,
    store_openrouter_key,
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
            car wraps AI harnesses (Copilot CLI / Claude Code) with OpenRouter
            model + provider controls.

            Default behavior:
            - Running `car` with no args launches the selected harness in
              interactive mode.
            - Running an unrecognized command passes args through to the
              selected harness.

            CLI mode examples:
            - `car --cli suggest "write a safer bash script"`
            - `car suggest "write a safer bash script"`
            - `car explain "docker compose run --rm car"`

            car management examples:
            - `car doctor`                     # verify harness/auth/key/cache
            - `car harness list`               # show available AI harnesses
            - `car harness use claude`          # switch to Claude Code
            - `car --harness`                   # pick harness interactively
            - `car model list`                 # show cached models/pricing
            - `car model list --provider=openai,google`
            - `car model refresh`              # force refresh pricing cache
            - `car provider list`              # show available providers
            - `car --update`                   # re-run installer update flow

            Common workflows:
            - First run: `car doctor` -> `car model refresh` -> `car`
            - Daily use: run `car`, then use `suggest` or `explain` flows
            - Change model: `car model list` then `car model use <model_id>`
            - Favorite model: `car model favorite-add <model_id>`
            - Lock provider: `car provider lock <provider>`
            - Switch harness: `car harness use claude`

            Troubleshooting:
            - Missing auth: run `gh auth login` (for Copilot)
            - Missing key: store in mattstash or set OPENROUTER_API_KEY
            - Empty cache: run `car model refresh`
            - Update wrapper/tools: run `car --update`
            """
        ).strip(),
    )
    sub = parser.add_subparsers(dest="command")

    model = sub.add_parser("model", help="Model management")
    model_sub = model.add_subparsers(dest="action")

    model_list = model_sub.add_parser("list", help="List cached models")
    model_list.add_argument(
        "--provider",
        default="",
        help="Comma-separated provider filter, e.g. openai,google",
    )
    model_ls = model_sub.add_parser("ls", help="Alias for list")
    model_ls.add_argument(
        "--provider",
        default="",
        help="Comma-separated provider filter, e.g. openai,google",
    )
    model_sub.add_parser("refresh", help="Refresh model cache from OpenRouter")
    model_sub.add_parser("current", help="Show current model")
    model_sub.add_parser("favorites", help="List favorite models")

    use = model_sub.add_parser("use", help="Set selected model")
    use.add_argument("model_id")
    model_set = model_sub.add_parser("set", help="Alias for use")
    model_set.add_argument("model_id")
    fav_add = model_sub.add_parser("favorite-add", help="Add model to favorites")
    fav_add.add_argument("model_id")
    fav_rm = model_sub.add_parser("favorite-remove", help="Remove model from favorites")
    fav_rm.add_argument("model_id")
    fav_use = model_sub.add_parser("favorite-use", help="Use favorite model by id")
    fav_use.add_argument("model_id")

    provider = sub.add_parser("provider", help="Provider lock commands")
    provider_sub = provider.add_subparsers(dest="action")
    lock = provider_sub.add_parser(
        "lock",
        help="Lock model selection to provider",
    )
    lock.add_argument("provider")
    mode = provider_sub.add_parser("mode", help="Set provider lock mode")
    mode.add_argument("value", choices=["strict", "prefer"])
    route = provider_sub.add_parser("route", help="Set routing mode")
    route.add_argument("value", choices=["model", "provider"])
    provider_sub.add_parser("list", help="List available providers")
    provider_sub.add_parser("ls", help="Alias for list")
    provider_sub.add_parser("unlock", help="Clear provider lock")
    provider_sub.add_parser("current", help="Show current provider lock")

    key = sub.add_parser("key", help="API key commands")
    key_sub = key.add_subparsers(dest="action")
    key_sub.add_parser("verify", help="Verify resolved OpenRouter API key")
    key_set = key_sub.add_parser("set", help="Store OpenRouter API key")
    key_set.add_argument(
        "--value",
        default="",
        help="Key value (omit to enter securely via prompt)",
    )
    key_set.add_argument(
        "--key-name",
        default="",
        help="Override mattstash key name for this set operation",
    )

    sub.add_parser("env", help="Show resolved provider environment")
    sub.add_parser("doctor", help="Check installation and auth")
    sub.add_parser("tui", help="Open Textual model selector")
    sub.add_parser("config", help="Print state file path")

    harness_parser = sub.add_parser("harness", help="AI harness selection")
    harness_sub = harness_parser.add_subparsers(dest="action")
    harness_sub.add_parser("list", help="List available AI harnesses")
    harness_sub.add_parser("ls", help="Alias for list")
    harness_use = harness_sub.add_parser("use", help="Set active harness")
    harness_use.add_argument("name", choices=["copilot", "claude"])
    harness_sub.add_parser("current", help="Show current harness")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()

    if argv and argv[0] == "--update":
        return handle_update()

    if argv and argv[0] == "--cli":
        return launch_copilot(argv[1:], backend="gh")

    if argv and argv[0] in {"-h", "--help", "help"}:
        parser.print_help()
        return 0

    if not argv:
        return launch_harness([])

    # ── --harness flag (interactive picker or direct set) ──────────────
    if argv and argv[0] == "--harness":
        if len(argv) == 1:
            # No harness specified — interactive selection
            return handle_harness_pick()
        # Direct set: car --harness copilot [rest...]
        harness_name = argv[1]
        return handle_harness_set_and_launch(harness_name, argv[2:])

    if argv == ["model"]:
        try:
            parser.parse_args(["model", "--help"])
        except SystemExit:
            return 0

    if argv == ["key"]:
        try:
            parser.parse_args(["key", "--help"])
        except SystemExit:
            return 0

    known = {
        "model", "provider", "key", "env",
        "doctor", "tui", "config", "harness",
    }
    if argv[0] in known:
        args = parser.parse_args(argv)
        return dispatch_subcommand(args)

    return launch_harness(argv)


def _repo_root_for_update() -> Path | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "install.sh").exists():
            return parent
    return None


def handle_update() -> int:
    repo_root = _repo_root_for_update()
    if repo_root is None:
        console.print(
            "Update unavailable: no git checkout found for this install.",
            style="red",
        )
        console.print(
            "Use the installed wrapper command `car --update` instead.",
        )
        return 1

    console.print(f"Updating car from: {repo_root}")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "pull", "--ff-only"],
            check=False,
        )
    except FileNotFoundError:
        console.print("git not found in PATH", style="red")
        return 1

    if result.returncode != 0:
        console.print(
            "Update failed (git pull returned non-zero)",
            style="red",
        )
        return result.returncode or 1

    console.print("Update complete.")
    return 0


def dispatch_subcommand(args: argparse.Namespace) -> int:
    state = load_state()

    if args.command == "model":
        return handle_model(state, args)
    if args.command == "provider":
        return handle_provider(state, args)
    if args.command == "key":
        return handle_key(state, args)
    if args.command == "env":
        return handle_env(state)
    if args.command == "doctor":
        return handle_doctor(state)
    if args.command == "tui":
        return handle_tui(state)
    if args.command == "config":
        return handle_config()
    if args.command == "harness":
        return handle_harness(state, args)
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

        provider_arg = getattr(args, "provider", "")
        if provider_arg:
            rows = filter_models_by_provider_arg(rows, provider_arg)
            print_models(rows, refreshed_at, None)
            console.print(f"Provider filter: {provider_arg}")
            return 0

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

    if action in {"use", "set"}:
        state.selected_model = normalize_model_selection(args.model_id)
        save_state(state)
        console.print(f"Selected model: {state.selected_model}")
        return 0

    if action == "current":
        console.print(selected_model(state))
        return 0

    if action == "favorites":
        if not state.favorite_models:
            console.print("No favorite models set")
            return 0
        for model_id in state.favorite_models:
            console.print(model_id)
        return 0

    if action == "favorite-add":
        if args.model_id not in state.favorite_models:
            state.favorite_models.append(args.model_id)
            save_state(state)
        console.print(f"Added favorite: {args.model_id}")
        return 0

    if action == "favorite-remove":
        state.favorite_models = [
            m for m in state.favorite_models if m != args.model_id
        ]
        save_state(state)
        console.print(f"Removed favorite: {args.model_id}")
        return 0

    if action == "favorite-use":
        if args.model_id not in state.favorite_models:
            console.print(f"Not in favorites: {args.model_id}")
            return 1
        state.selected_model = args.model_id
        save_state(state)
        console.print(f"Selected model: {args.model_id}")
        return 0

    console.print("Unknown model action")
    return 1


def handle_provider(state: CarState, args: argparse.Namespace) -> int:
    action = args.action or "current"

    if action in {"list", "ls"}:
        rows, _ = load_cached_models()
        if not rows:
            console.print("Model cache missing. Refreshing now...")
            try:
                rows = refresh_models(state.openrouter_base_url)
            except OpenRouterError as exc:
                console.print(f"Refresh failed: {exc}")
                return 1

        providers = sorted({row.provider for row in rows})
        for provider in providers:
            console.print(provider)
        return 0

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

    if action == "route":
        state.route_mode = args.value
        save_state(state)
        console.print(f"Route mode: {state.route_mode}")
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
        console.print(f"route_mode={state.route_mode}")
        return 0

    return 1


def handle_env(state: CarState) -> int:
    key = resolve_openrouter_key(state)
    model = selected_model(state)
    harness = state.harness
    is_claude = harness == "claude"

    console.print(f"CAR_HARNESS={harness}")

    url_var = (
        "ANTHROPIC_BASE_URL" if is_claude else "COPILOT_PROVIDER_BASE_URL"
    )
    model_var = "ANTHROPIC_MODEL" if is_claude else "COPILOT_MODEL"
    key_var = "ANTHROPIC_API_KEY" if is_claude else "COPILOT_PROVIDER_API_KEY"

    console.print(f"{url_var}={state.openrouter_base_url}")
    console.print(f"{model_var}={model}")
    console.print(f"CAR_PROVIDER_LOCK={state.provider_lock or ''}")
    console.print(f"CAR_ROUTE_MODE={state.route_mode}")

    if key:
        console.print(f"{key_var}=<set>")
    else:
        console.print(f"{key_var}=<unset>")
        if state.key_helper:
            console.print(f"Hint: run {state.key_helper}")
    return 0


def handle_key(state: CarState, args: argparse.Namespace) -> int:
    action = args.action or "verify"

    if action == "set":
        key_name_override = getattr(args, "key_name", "").strip()
        if key_name_override.startswith("sk-or-v1-"):
            console.print(
                "That looks like an API key, not a name. "
                "Using default key name instead: openrouter_api_key",
                style="yellow",
            )
            key_name_override = ""
        value = getattr(args, "value", "").strip()

        if not value:
            try:
                value = getpass.getpass("OpenRouter API key: ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("Key entry cancelled", style="yellow")
                return 1

        if not value:
            console.print("OpenRouter API key is empty", style="red")
            return 1

        try:
            key_name = store_openrouter_key(
                state,
                value,
                key_name=key_name_override or None,
            )
        except RuntimeError as exc:
            console.print(f"Key set failed: {exc}", style="red")
            return 1

        if key_name_override and key_name_override != state.key_name:
            state.key_name = key_name_override
            save_state(state)

        console.print(f"Stored OpenRouter key in mattstash as: {key_name}")
        console.print("Run 'car key verify' to validate it against OpenRouter")
        return 0

    if action != "verify":
        console.print("Unknown key action")
        return 1

    key, source = resolve_openrouter_key_with_source(state)
    if not key:
        console.print("OpenRouter key not found.", style="red")
        if state.key_helper:
            console.print(f"Run: {state.key_helper}")
        return 1

    try:
        payload = verify_api_key(state.openrouter_base_url, key)
    except OpenRouterError as exc:
        console.print(f"Key verification failed: {exc}", style="red")
        if source:
            console.print(f"Resolved key source: {source}")
        if "rejected" in str(exc).lower() and source in {
            "CAR_OPENROUTER_API_KEY",
            "OPENROUTER_API_KEY",
            "COPILOT_PROVIDER_API_KEY",
        }:
            console.print(
                "Hint: an environment variable is overriding mattstash. "
                "Unset it or update that env var value.",
                style="yellow",
            )
        return 1

    details = payload.get("data") if isinstance(payload, dict) else None
    label = details.get("label") if isinstance(details, dict) else None
    usage = details.get("usage") if isinstance(details, dict) else None

    console.print("OpenRouter API key is valid", style="green")
    if source:
        console.print(f"Resolved key source: {source}")
    if label:
        console.print(f"Key label: {label}")
    if usage is not None:
        console.print(f"Usage: {usage}")
    return 0


def handle_doctor(state: CarState) -> int:
    harness = state.harness
    checks: list = []

    available = detect_available_harnesses()
    checks.append(_doctor(
        "harness",
        harness in available,
        f"Selected: {harness_display_name(harness)}; "
        f"available: {', '.join(available) if available else 'none'}",
    ))

    if harness == "copilot":
        checks += [
            check_gh_installed(),
            check_copilot_extension(),
            check_gh_auth(),
        ]
    else:
        checks.append(check_claude_installed())

    key = resolve_openrouter_key(state)
    checks.append(_doctor(
        "openrouter-key",
        bool(key),
        "Key resolved" if key else "No key found in env or mattstash",
    ))

    rows, _ = load_cached_models()
    cache_detail = (
        f"{len(rows)} cached models"
        if rows else "Cache empty; run car model refresh"
    )
    checks.append(_doctor("model-cache", bool(rows), cache_detail))

    model = selected_model(state)
    prompt_tokens, output_tokens = resolve_model_token_limits(model)
    has_limits = prompt_tokens is not None and output_tokens is not None
    harness_label = "Copilot" if harness == "copilot" else "Claude Code"
    if has_limits:
        limit_detail = (
            f"prompt={prompt_tokens}, output={output_tokens} for {model}"
        )
    else:
        limit_detail = (
            f"No cached token limits for {model}; "
            f"{harness_label} may use provider defaults"
        )
    checks.append(_doctor("model-token-limits", has_limits, limit_detail))

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

    outcome = run_tui(
        rows,
        selected_model(state),
        state.provider_lock,
        state.favorite_models,
        state.route_mode,
        state.harness,
    )
    if not outcome:
        return 0

    model_id, provider_lock, route_mode, favorites, harness = outcome
    state.selected_model = model_id
    state.provider_lock = provider_lock
    state.route_mode = route_mode
    state.favorite_models = favorites
    state.harness = harness
    save_state(state)

    console.print(f"Selected model: {model_id}")
    console.print(f"Provider lock: {provider_lock or '<none>'}")
    console.print(f"Route mode: {route_mode}")
    return launch_harness([])


def handle_config() -> int:
    console.print(str(state_path()))
    return 0


def launch_harness(
    harness_args: list[str],
    backend: str | None = None,
) -> int:
    state = load_state()
    harness: HarnessName = state.harness  # type: ignore[assignment]
    key = resolve_openrouter_key(state)
    if not key:
        console.print("OpenRouter key not found.", style="red")
        if state.key_helper:
            console.print(f"Run: {state.key_helper}")
        return 1

    ensure_models_fresh(state)

    model = selected_model(state)
    env = build_harness_env(harness, state.openrouter_base_url, key, model)

    max_prompt_tokens, max_output_tokens = resolve_model_token_limits(model)
    if harness == "copilot":
        if max_prompt_tokens is not None:
            env["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] = str(max_prompt_tokens)
        if max_output_tokens is not None:
            env["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] = str(max_output_tokens)

    if state.provider_lock:
        env["CAR_PROVIDER_LOCK"] = state.provider_lock
        env["CAR_PROVIDER_LOCK_MODE"] = state.provider_lock_mode
    env["CAR_ROUTE_MODE"] = state.route_mode

    return exec_harness(harness, harness_args, env, backend=backend)


# Backward-compatible alias used by `--cli` and tests.
launch_copilot = launch_harness


# ── Harness subcommand handlers ──────────────────────────────────────────────


_CO = "curl -fsSL"


def handle_harness(state: CarState, args: argparse.Namespace) -> int:
    action = args.action or "current"

    if action in {"list", "ls"}:
        available = detect_available_harnesses()
        if not available:
            console.print("No AI harnesses detected", style="yellow")
            console.print(
                "Install Copilot CLI: "
                + _CO + " https://gh.io/copilot-install | bash"
            )
            console.print(
                "Install Claude Code: "
                + _CO + " https://claude.ai/install.sh | bash"
            )
            return 1
        for h in available:
            marker = " *" if h == state.harness else "  "
            console.print(f"{marker} {h}  ({harness_display_name(h)})")
        return 0

    if action == "use":
        name = args.name
        # argparse already enforces choices=["copilot","claude"] so this
        # branch is a safety net in case handle_harness is called directly.
        if name not in {"copilot", "claude"}:
            console.print(f"Unknown harness: {name}", style="red")
            return 1
        available = detect_available_harnesses()
        if name not in available:
            console.print(
                f"Harness '{name}' is not installed.", style="yellow"
            )
            if name == "claude":
                console.print(
                    "Install: curl -fsSL https://claude.ai/install.sh | bash"
                )
            else:
                console.print(
                    "Install: gh extension install github/gh-copilot"
                )
            console.print(
                f"To force-set: CAR_HARNESS={name} car harness use {name}"
            )
            return 1
        state.harness = name
        save_state(state)
        console.print(f"Active harness: {harness_display_name(name)}")
        return 0

    if action == "current":
        console.print(f"Harness: {harness_display_name(state.harness)}")
        available = detect_available_harnesses()
        console.print(
            f"Available: {', '.join(available) if available else 'none'}"
        )
        return 0

    return 1


def handle_harness_pick() -> int:
    """Interactive picker for `car --harness` with no arg."""
    available = detect_available_harnesses()
    if not available:
        console.print("No AI harnesses detected.", style="red")
        console.print(
            "Install Copilot CLI: "
            + _CO + " https://gh.io/copilot-install | bash"
        )
        console.print(
            "Install Claude Code: "
            + _CO + " https://claude.ai/install.sh | bash"
        )
        return 1

    if len(available) == 1:
        state = load_state()
        state.harness = available[0]
        save_state(state)
        console.print(
            f"Only one harness available. Set to: "
            f"{harness_display_name(available[0])}"
        )
        return 0

    console.print("Available AI harnesses:")
    for i, h in enumerate(available, 1):
        console.print(f"  {i}) {harness_display_name(h)}")

    try:
        # Use sys.stderr so the prompt is visible even when stdout is piped.
        prompt = f"Select harness [1-{len(available)}]: "
        sys.stderr.write(prompt)
        sys.stderr.flush()
        choice = input().strip()
        idx = int(choice) - 1
    except (EOFError, KeyboardInterrupt):
        console.print("Selection cancelled", style="yellow")
        return 1
    except ValueError:
        console.print("Invalid choice", style="red")
        return 1

    if idx < 0 or idx >= len(available):
        console.print("Invalid choice", style="red")
        return 1

    state = load_state()
    state.harness = available[idx]
    save_state(state)
    console.print(f"Active harness: {harness_display_name(available[idx])}")
    return 0


def handle_harness_set_and_launch(
    name: str,
    remaining_args: list[str],
) -> int:
    """Set harness from `car --harness <name> [args...]` and launch if args."""
    if name not in {"copilot", "claude"}:
        console.print(f"Unknown harness: {name}", style="red")
        return 1

    state = load_state()
    state.harness = name
    save_state(state)
    console.print(f"Active harness: {harness_display_name(name)}")

    available = detect_available_harnesses()
    if name not in available:
        console.print(
            f"Warning: '{name}' does not appear to be installed.",
            style="yellow",
        )

    if remaining_args:
        return launch_harness(remaining_args)
    return 0


def _doctor(name: str, ok: bool, detail: str) -> DoctorResult:
    return DoctorResult(name=name, ok=ok, detail=detail)


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


def filter_models_by_provider_arg(rows, provider_arg: str):
    providers = {
        value.strip().lower()
        for value in provider_arg.split(",")
        if value.strip()
    }
    if not providers:
        return rows
    return [row for row in rows if row.provider.lower() in providers]


def resolve_model_token_limits(model_id: str) -> tuple[int | None, int | None]:
    rows, _ = load_cached_models()

    needle = model_id.strip().lower()

    for row in rows:
        if row.model_id.lower() == needle:
            return row.max_prompt_tokens, row.max_output_tokens

    # Support short-form selections (e.g., "deepseek-v4-pro") by matching
    # unique provider-qualified IDs that share the same model suffix.
    suffix_matches = [
        row
        for row in rows
        if row.model_id.lower().split("/", 1)[-1] == needle
    ]
    if len(suffix_matches) == 1:
        row = suffix_matches[0]
        return row.max_prompt_tokens, row.max_output_tokens

    return None, None


def normalize_model_selection(model_id: str) -> str:
    rows, _ = load_cached_models()
    if not rows:
        return model_id

    needle = model_id.strip()
    if not needle:
        return model_id

    needle_lower = needle.lower()

    for row in rows:
        if row.model_id.lower() == needle_lower:
            return row.model_id

    suffix_matches = [
        row.model_id
        for row in rows
        if row.model_id.lower().split("/", 1)[-1] == needle_lower
    ]
    if len(suffix_matches) == 1:
        resolved = suffix_matches[0]
        console.print(
            f"[yellow]Warning:[/yellow] '{model_id}' is imprecise. "
            f"Using '{resolved}'."
        )
        return resolved

    suggestions = suggest_model_corrections(model_id, rows)
    if suggestions:
        console.print(
            f"[yellow]Warning:[/yellow] '{model_id}' was not found exactly. "
            f"Did you mean: {', '.join(suggestions)}"
        )

    return model_id


def suggest_model_corrections(model_id: str, rows, limit: int = 3) -> list[str]:
    needle = model_id.strip().lower()
    if not needle:
        return []

    scored: list[tuple[float, str]] = []
    for row in rows:
        full = row.model_id.lower()
        suffix = full.split("/", 1)[-1]
        score = max(
            difflib.SequenceMatcher(a=needle, b=full).ratio(),
            difflib.SequenceMatcher(a=needle, b=suffix).ratio(),
        )
        if needle in full or needle in suffix:
            score = max(score, 0.85)
        if score >= 0.6:
            scored.append((score, row.model_id))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))
    ordered: list[str] = []
    for _, model in scored:
        if model not in ordered:
            ordered.append(model)
        if len(ordered) >= limit:
            break
    return ordered
