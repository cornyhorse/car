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

Pass through arguments to gh copilot:

```bash
car suggest "write a safer bash script"
```

Model commands:

```bash
car model refresh
car model list
car model use openai/gpt-4o-mini
car model current
```

Provider lock commands:

```bash
car provider lock aws-bedrock
car provider mode strict
car provider current
car provider unlock
```

TUI selector:

```bash
car tui
```

Inside TUI:

- Arrow keys navigate providers/models.
- Enter selects model and exits.
- L toggles provider lock for current provider filter.
- Q exits.

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

State stores:

- openrouter_base_url
- default_model
- selected_model
- provider_lock
- provider_lock_mode
- key_name/mattstash settings

## Notes On Provider Lock

Provider lock currently enforces local selection/filtering policy.
It is useful when OpenRouter model IDs include provider prefixes
(for example aws-bedrock/*).

For strict upstream routing guarantees, provider-specific routing hints may need
to be passed directly to OpenRouter request payloads when that interface is
available in gh copilot integration.