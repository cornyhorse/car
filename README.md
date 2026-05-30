# car

car is a wrapper around GitHub Copilot CLI that injects OpenRouter settings,
persists model selection, and adds a Textual TUI for model/provider selection.

## What It Does

- Runs gh copilot with OpenRouter environment variables already set.
- Stores selected model and provider lock in local state.
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

Installer behavior:

- Installs or updates GitHub CLI + gh-copilot using https://gh.io/copilot-install
- Prompts for install mode (docker or venv) by default
- Clones or updates this repo at ~/.local/share/car
- Creates a shared tools venv at ~/.local/share/car/venv-tools
- Installs mattstash into that venv (no system Python install)
- Installs car into that venv when venv mode is selected
- Builds the Docker image in docker mode (skips rebuild when git ref and image are unchanged)
- Installs a wrapper command at ~/.local/bin/car for the selected mode
- Adds ~/.local/bin to both ~/.bashrc and ~/.zshrc when missing
- Offers an end-of-install key setup wizard using mattstash
- Refreshes model cache during install when possible (skips when cache already exists unless forced)

Non-interactive examples:

```bash
# Deterministic docker install without prompts
bash install.sh --mode docker --non-interactive --skip-configure-keys

# Host venv install and key setup wizard
bash install.sh --mode venv --configure-keys
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
```

When invoked via the generated `car` wrapper in docker mode, the container runs
as your host UID/GID to avoid root-owned files in `~/.config/car` and
`~/.cache/car`.

Optional mattstash container profile:

```bash
export KDBX_PASSWORD="..."
export MATTSTASH_API_KEY="..."
docker compose --profile mattstash up -d mattstash
```

## Key Setup

car resolves OpenRouter key in this order:

1. CAR_OPENROUTER_API_KEY
2. OPENROUTER_API_KEY
3. COPILOT_PROVIDER_API_KEY
4. mattstash get <key_name> --show-password (defaults to key name openrouter_api_key)

Installer key wizard flow:

1. Detects or initializes mattstash setup.
2. Prompts for key name (default openrouter_api_key).
3. Stores value via mattstash put <key_name> --value ...

If you prefer environment variables:

```bash
export OPENROUTER_API_KEY="..."
```

## Usage

Launch Copilot with configured settings:

```bash
car
```

Update car to latest configured repo ref:

```bash
car --update
```

`car --update` re-runs the installer in your current mode (docker or venv).

Pass through arguments to gh copilot:

```bash
car suggest "write a safer bash script"
car --cli suggest "force gh copilot backend"
```

Model commands:

```bash
car model refresh
car model list
car model use openai/gpt-4o-mini
car model current
car model favorites
car model favorite-add anthropic/claude-3-haiku
car model favorite-remove anthropic/claude-3-haiku
car model favorite-use anthropic/claude-3-haiku
```

Provider lock commands:

```bash
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
- Enter selects model and exits.
- F toggles favorite for selected model.
- L toggles provider lock for current provider filter.
- R toggles route mode:
	- model: select model independent of provider lock
	- provider: select model plus pinned provider lock
- A clears provider filter back to all.
- Q exits.

Favorites are shown at the top of the model table for quick switching.
Favorites also appear in the provider tree above the `all` entry for quick discovery.

Environment and diagnostics:

```bash
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

- openrouter_base_url
- default_model
- selected_model
- favorite_models
- provider_lock
- provider_lock_mode
- route_mode
- key_name/mattstash settings

## Notes On Provider Lock

Provider lock currently enforces local selection/filtering policy.
It is useful when OpenRouter model IDs include provider prefixes
(for example aws-bedrock/*).

For strict upstream routing guarantees, provider-specific routing hints may need
to be passed directly to OpenRouter request payloads when that interface is
available in gh copilot integration.