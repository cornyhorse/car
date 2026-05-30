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

This repo is configured for container-first usage.

Quick install via curl and bash:

```bash
curl -fsSL https://raw.githubusercontent.com/cornyhorse/car/main/install.sh | bash
```

Installer behavior:

- Clones or updates this repo at ~/.local/share/car
- Builds the Docker image for the car service
- Installs a wrapper command at ~/.local/bin/car
- Adds ~/.local/bin to both ~/.bashrc and ~/.zshrc when missing

1. Build image:

```bash
docker compose build
```

2. Run command examples:

```bash
docker compose run --rm car doctor
docker compose run --rm car model refresh
docker compose run --rm car model list
```

## Key Setup

car resolves OpenRouter key in this order:

1. CAR_OPENROUTER_API_KEY
2. OPENROUTER_API_KEY
3. COPILOT_PROVIDER_API_KEY
4. mattstash get <key_name> --show-password (defaults to key name openrouter_api_key)

If you use environment variables:

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

If you want local car command to run in Docker:

For bash (.bashrc):

```bash
car() {
	docker compose -f "$HOME/Documents/GitHub/car/docker-compose.yml" run --rm car "$@"
}
```

For zsh (.zshrc):

```bash
car() {
	docker compose -f "$HOME/Documents/GitHub/car/docker-compose.yml" run --rm car "$@"
}
```

If you prefer host install instead of Docker:

```bash
pip install -e .
```

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