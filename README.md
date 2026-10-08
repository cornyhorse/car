# car

car wraps AI coding assistants (GitHub Copilot CLI and Claude Code CLI) with
OpenRouter model + provider controls, persistent state, and a Textual TUI.

## What It Does

- Supports two AI harnesses: **Copilot CLI** (gh-copilot) and **Claude Code CLI**.
- Routes both harnesses through OpenRouter by injecting the right env vars.
- Stores selected harness, model, and provider lock in local state.
- Fetches and caches OpenRouter model metadata (pricing and context length).
- Provides a TUI with provider list on the left and model table on the right.
- Supports optional provider lock (for example aws-bedrock) when selecting models.

## Install

The installer supports both Docker and host-venv workflows.

Quick install via curl and bash:

```bash
curl -fsSL https://raw.githubusercontent.com/cornyhorse/car/main/install.sh | bash
```

This launches the interactive installer by default.
Use `--non-interactive` to disable prompts.

Requirements: `git`, `curl` and **Python 3.11 or newer** as `python3` on `PATH`, in both docker and venv
mode. The installer checks the Python version first and stops with a message (exit 1) before it prompts,
clones, builds or installs anything when it is older. Docker mode needs it too because the shared tools
venv (which holds the `mattstash` CLI) is always built with the host `python3`, even though car itself then
runs in a container. An existing tools venv that was built with an older Python is refused the same way:
remove `~/.local/share/car/venv-tools` and re-run with a newer `python3`. On macOS the system `python3`
is 3.9, so use e.g. `brew install python@3.12`.

Installer behavior:

- Prompts for which harness(es) to install: Copilot CLI, Claude Code CLI, or both
- Installs or updates GitHub CLI + gh-copilot using https://gh.io/copilot-install
- Installs Claude Code CLI using https://claude.ai/install.sh when selected
- Prompts for install mode (docker or venv) by default
- Clones or updates this repo at ~/.local/share/car
- Creates a shared tools venv at ~/.local/share/car/venv-tools
- Installs `mattstash>=0.2,<0.3` into that venv (no system Python install); override with `CAR_MATTSTASH_PACKAGE`
- Installs car into that venv when venv mode is selected
- Builds the Docker image in docker mode (skips rebuild when git ref and image are unchanged)
- Installs a wrapper command at ~/.local/bin/car for the selected mode
- Adds ~/.local/bin to both ~/.bashrc and ~/.zshrc when missing
- Offers an end-of-install key setup wizard using mattstash
- Refreshes model cache during install when possible (skips when cache already exists unless forced)

Non-interactive examples:

```bash
# Deterministic docker install with both harnesses, no prompts
bash install.sh --mode docker --harness both --non-interactive --skip-configure-keys

# Install Copilot CLI only (default) in venv mode with key setup
bash install.sh --mode venv --harness copilot --configure-keys

# Install Claude Code CLI only
bash install.sh --harness claude
```

Force refresh:

```bash
bash install.sh --force
```

Docker commands:

```bash
docker compose run --rm car doctor
docker compose run --rm car model refresh
docker compose run --rm car model list
# Run full test suite in container
docker compose run --rm --entrypoint python car -m pytest -q
# Run only integration-marked tests
docker compose run --rm --entrypoint python car -m pytest -q -m integration
```

When invoked via the generated `car` wrapper in docker mode, the container runs
as your host UID/GID to avoid root-owned files in `~/.config/car` and
`~/.cache/car`.

Optional mattstash container profile (pinned to the mattstash `v0.2.0` server image):

```bash
export KDBX_PASSWORD="..."
export MATTSTASH_API_KEY="$(openssl rand -base64 32)"
docker compose --profile mattstash up -d mattstash
```

Requirements of the mattstash 0.2 server:

- The database must already exist at `~/.credentials/mattstash.kdbx`; the server never creates one
  (create it with `mattstash --db ~/.credentials/mattstash.kdbx setup`).
- `KDBX_PASSWORD` is the database master password. The server does not read the `.mattstash.txt` sidecar.
- `MATTSTASH_API_KEY` must be at least 32 characters.
- The server is read-only (the database is mounted `:ro`). car itself only uses the `mattstash` CLI against
  the local database and never writes through the server.

## Key Setup

car resolves OpenRouter key in this order:

1. CAR_OPENROUTER_API_KEY
2. OPENROUTER_API_KEY
3. COPILOT_PROVIDER_API_KEY
4. mattstash get <key_name> --show-password (defaults to key name openrouter_api_key)

Installer key wizard flow:

1. Detects or initializes mattstash setup (`mattstash setup --sidecar`, which stores a generated master
   password next to the database so car can read the key non-interactively; mattstash 0.2 no longer
   creates a database on first use).
2. Prompts for key name (default openrouter_api_key).
3. Stores value via mattstash put <key_name> --value ...

If you prefer environment variables:

```bash
export OPENROUTER_API_KEY="..."
```

## Usage

Launch the active AI harness with configured settings:

```bash
car
```

Update car to latest configured repo ref:

```bash
car --update
```

`car --update` re-runs the installer in your current mode (docker or venv).
It forces a rebuild/reinstall so code changes are picked up immediately.

Pass through arguments to the active harness:

```bash
car suggest "write a safer bash script"     # Copilot
car --cli suggest "force gh copilot backend" # Copilot, gh backend
```

Harness selection:

```bash
car harness list               # show detected harnesses (* = active)
car harness use copilot        # switch to Copilot CLI
car harness use claude         # switch to Claude Code CLI
car harness current            # show active harness
car --harness                  # interactive picker (if both installed)
car --harness claude           # set claude and return to shell
```

Model commands:

```bash
car model refresh
car model list
car model ls
car model list --provider=openai,google
car model use openai/gpt-4o-mini
car model set openai/gpt-4o-mini
car model current
car model favorites
car model favorite-add anthropic/claude-3-haiku
car model favorite-remove anthropic/claude-3-haiku
car model favorite-use anthropic/claude-3-haiku
```

Provider lock commands:

```bash
car provider list
car provider ls
car provider lock aws-bedrock
car provider mode strict
car provider route model
car provider route provider
car provider current
car provider unlock
```

TUI selector:

```bash
car tui
```

Inside TUI:

- Arrow keys navigate providers/models.
- Esc returns focus to the provider list.
- Selecting the root Providers node keeps the list expanded.
- Enter selects the model, saves it, closes the TUI, and launches the active harness.
- F toggles favorite for selected model.
- H toggles active harness between Copilot and Claude Code.
- L toggles provider lock for current provider filter.
- R toggles route mode:
	- model: select model independent of provider lock
	- provider: select model plus pinned provider lock
- A clears provider filter back to all.
- Q exits.

Favorites are shown at the top of the model table for quick switching.
Favorites also appear as a `Favorites` branch under `Providers`, above the `all` entry for quick discovery.

Environment and diagnostics:

```bash
car key set
car key verify
car env
car doctor
car config
```

## Shell Setup

The installer writes ~/.local/bin/car and updates PATH for bash/zsh when needed.
The wrapper uses your selected mode:

- docker mode: runs docker compose run --rm car ...
- venv mode: runs the host venv CLI at ~/.local/share/car/venv-tools/bin/car

## State And Cache

- State file: ~/.config/car/state.json
- Model cache: ~/.cache/car/models.json

Model cache refresh behavior:

- `car` refreshes model metadata automatically when cache is missing or older than 24 hours.
- `car model refresh` always forces a refresh immediately.

State stores:

- harness (copilot or claude, default: copilot)
- openrouter_base_url
- default_model
- selected_model
- favorite_models
- provider_lock
- provider_lock_mode
- route_mode
- key_name/mattstash settings

Override harness at runtime without saving:

```bash
CAR_HARNESS=claude car
```

## Claude Code + OpenRouter

When harness is `claude`, car sets these env vars before launching Claude Code:

| Variable | Value |
|---|---|
| `ANTHROPIC_BASE_URL` | OpenRouter base URL (e.g. `https://openrouter.ai/api/v1`) |
| `ANTHROPIC_API_KEY` | Your OpenRouter API key |
| `ANTHROPIC_MODEL` | Selected model ID (e.g. `anthropic/claude-opus-4-5`) |

This routes Claude Code through OpenRouter, giving you the same model/provider
controls as Copilot mode. Run `car model refresh` and `car model list` to browse
available models regardless of which harness is active.

## Notes On Provider Lock

Provider lock currently enforces local selection/filtering policy.
It is useful when OpenRouter model IDs include provider prefixes
(for example aws-bedrock/*).

For strict upstream routing guarantees, provider-specific routing hints may need
to be passed directly to OpenRouter request payloads when that interface is
available in gh copilot integration.