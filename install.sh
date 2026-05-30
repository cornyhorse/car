#!/usr/bin/env bash
set -euo pipefail

# Public defaults for this repository; override with env vars if needed.
CAR_GITHUB_REPO="${CAR_GITHUB_REPO:-cornyhorse/car}"
CAR_GIT_REF="${CAR_GIT_REF:-main}"
CAR_HOME="${CAR_HOME:-$HOME/.local/share/car}"
CAR_BIN_DIR="${CAR_BIN_DIR:-$HOME/.local/bin}"
CAR_WRAPPER="$CAR_BIN_DIR/car"
CAR_COPILOT_INSTALL_URL="${CAR_COPILOT_INSTALL_URL:-https://gh.io/copilot-install}"
CAR_DOCKER_IMAGE="${CAR_DOCKER_IMAGE:-car-dev:latest}"
CAR_INSTALL_MODE="${CAR_INSTALL_MODE:-ask}"
CAR_NONINTERACTIVE="${CAR_NONINTERACTIVE:-0}"
CAR_FORCE="${CAR_FORCE:-0}"
CAR_CONFIGURE_KEYS="${CAR_CONFIGURE_KEYS:-ask}"
CAR_ENABLE_MATTSTASH_PROFILE="${CAR_ENABLE_MATTSTASH_PROFILE:-ask}"
CAR_TOOLS_VENV="${CAR_TOOLS_VENV:-$HOME/.local/share/car/venv-tools}"
CAR_MATTSTASH_PACKAGE="${CAR_MATTSTASH_PACKAGE:-mattstash}"
CAR_MATTSTASH_KEY_NAME="${CAR_MATTSTASH_KEY_NAME:-openrouter_api_key}"

CAR_TOOLS_PYTHON="$CAR_TOOLS_VENV/bin/python"
CAR_TOOLS_PIP="$CAR_TOOLS_VENV/bin/pip"
CAR_TOOLS_CAR="$CAR_TOOLS_VENV/bin/car"
CAR_MATTSTASH_CLI="$CAR_TOOLS_VENV/bin/mattstash"

log() {
  printf '[car-install] %s\n' "$*"
}

warn() {
  printf '[car-install] WARNING: %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

usage() {
  cat <<EOF
Usage: install.sh [options]

Options:
  --mode docker|venv           Install mode.
  --non-interactive            Disable all prompts.
  --force                      Force reinstall/rebuild where supported.
  --configure-keys             Run key setup wizard at the end.
  --skip-configure-keys        Skip key setup wizard.
  --with-mattstash-docker      Recommend mattstash compose profile at end.
  --without-mattstash-docker   Skip mattstash compose profile guidance.
  --help                       Show this help.
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --mode)
        shift
        CAR_INSTALL_MODE="${1:-}"
        ;;
      --non-interactive)
        CAR_NONINTERACTIVE="1"
        ;;
      --force)
        CAR_FORCE="1"
        ;;
      --configure-keys)
        CAR_CONFIGURE_KEYS="1"
        ;;
      --skip-configure-keys)
        CAR_CONFIGURE_KEYS="0"
        ;;
      --with-mattstash-docker)
        CAR_ENABLE_MATTSTASH_PROFILE="1"
        ;;
      --without-mattstash-docker)
        CAR_ENABLE_MATTSTASH_PROFILE="0"
        ;;
      --help)
        usage
        exit 0
        ;;
      *)
        printf 'Unknown argument: %s\n' "$1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done
}

can_prompt() {
  [ "$CAR_NONINTERACTIVE" != "1" ] && [ -r /dev/tty ] && [ -w /dev/tty ]
}

prompt_yes_no() {
  local message="$1"
  local default="$2"
  local answer=""

  if ! can_prompt; then
    [ "$default" = "y" ]
    return
  fi

  if [ "$default" = "y" ]; then
    read -r -p "$message [Y/n]: " answer </dev/tty
    answer="${answer:-y}"
  else
    read -r -p "$message [y/N]: " answer </dev/tty
    answer="${answer:-n}"
  fi

  case "$answer" in
    y|Y|yes|YES)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

choose_install_mode() {
  if [ "$CAR_INSTALL_MODE" = "ask" ]; then
    if can_prompt; then
      printf '\n[car-install] Select install mode:\n'
      printf '  1) docker (wrapper runs docker compose)\n'
      printf '  2) venv   (wrapper runs host venv CLI)\n'
      read -r -p 'Choice [1/2] (default 1): ' choice </dev/tty
      case "$choice" in
        2)
          CAR_INSTALL_MODE="venv"
          ;;
        *)
          CAR_INSTALL_MODE="docker"
          ;;
      esac
    else
      CAR_INSTALL_MODE="docker"
      log "No interactive terminal detected; defaulting to docker mode"
    fi
  fi

  if [ "$CAR_INSTALL_MODE" != "docker" ] && [ "$CAR_INSTALL_MODE" != "venv" ]; then
    printf 'Invalid install mode: %s\n' "$CAR_INSTALL_MODE" >&2
    exit 1
  fi

  log "Install mode: $CAR_INSTALL_MODE"
}

append_path_export_if_missing() {
  local rc_file="$1"
  local line="export PATH=\"$CAR_BIN_DIR:\$PATH\""

  if [ ! -f "$rc_file" ]; then
    touch "$rc_file"
  fi

  if ! grep -Fq "$line" "$rc_file"; then
    printf '\n# Added by car installer\n%s\n' "$line" >>"$rc_file"
    log "Updated $rc_file to include $CAR_BIN_DIR in PATH"
  fi
}

write_docker_wrapper() {
  mkdir -p "$CAR_BIN_DIR"
  cat >"$CAR_WRAPPER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

CAR_HOME="${CAR_HOME:-$HOME/.local/share/car}"
CAR_TOOLS_VENV="${CAR_TOOLS_VENV:-$HOME/.local/share/car/venv-tools}"
CAR_MATTSTASH_CLI="${CAR_MATTSTASH_CLI:-$CAR_TOOLS_VENV/bin/mattstash}"
CAR_MATTSTASH_KEY_NAME="${CAR_MATTSTASH_KEY_NAME:-openrouter_api_key}"

if [ "${1:-}" = "--update" ]; then
  shift
  exec bash "$CAR_HOME/install.sh" --mode docker --force "$@"
fi

if [ -z "${CAR_OPENROUTER_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${COPILOT_PROVIDER_API_KEY:-}" ]; then
  if [ -x "$CAR_MATTSTASH_CLI" ]; then
    token="$("$CAR_MATTSTASH_CLI" get "$CAR_MATTSTASH_KEY_NAME" --show-password 2>/dev/null || true)"
    token="$(printf '%s' "$token" | tr -d '\r')"
    if [ -n "$token" ]; then
      export COPILOT_PROVIDER_API_KEY="$token"
    fi
  fi
fi

if docker compose version >/dev/null 2>&1; then
  exec docker compose -f "$CAR_HOME/docker-compose.yml" run --rm --user "$(id -u):$(id -g)" car "$@"
elif command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose -f "$CAR_HOME/docker-compose.yml" run --rm --user "$(id -u):$(id -g)" car "$@"
else
  echo "Docker Compose is required but was not found." >&2
  exit 1
fi
EOF
  chmod +x "$CAR_WRAPPER"
}

write_venv_wrapper() {
  mkdir -p "$CAR_BIN_DIR"
  cat >"$CAR_WRAPPER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

CAR_HOME="${CAR_HOME:-$HOME/.local/share/car}"
CAR_TOOLS_VENV="${CAR_TOOLS_VENV:-$HOME/.local/share/car/venv-tools}"
CAR_TOOLS_CAR="${CAR_TOOLS_CAR:-$CAR_TOOLS_VENV/bin/car}"
CAR_MATTSTASH_CLI="${CAR_MATTSTASH_CLI:-$CAR_TOOLS_VENV/bin/mattstash}"
CAR_MATTSTASH_KEY_NAME="${CAR_MATTSTASH_KEY_NAME:-openrouter_api_key}"

if [ "${1:-}" = "--update" ]; then
  shift
  exec bash "$CAR_HOME/install.sh" --mode venv --force "$@"
fi

export PATH="$CAR_TOOLS_VENV/bin:$PATH"

if [ -z "${CAR_OPENROUTER_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${COPILOT_PROVIDER_API_KEY:-}" ]; then
  if [ -x "$CAR_MATTSTASH_CLI" ]; then
    token="$("$CAR_MATTSTASH_CLI" get "$CAR_MATTSTASH_KEY_NAME" --show-password 2>/dev/null || true)"
    token="$(printf '%s' "$token" | tr -d '\r')"
    if [ -n "$token" ]; then
      export COPILOT_PROVIDER_API_KEY="$token"
    fi
  fi
fi

if [ ! -x "$CAR_TOOLS_CAR" ]; then
  echo "car executable was not found at $CAR_TOOLS_CAR" >&2
  exit 1
fi

exec "$CAR_TOOLS_CAR" "$@"
EOF
  chmod +x "$CAR_WRAPPER"
}

write_wrapper() {
  if [ "$CAR_INSTALL_MODE" = "venv" ]; then
    write_venv_wrapper
  else
    write_docker_wrapper
  fi
}

clone_or_update_repo() {
  local repo_url="https://github.com/${CAR_GITHUB_REPO}.git"

  if [ -d "$CAR_HOME/.git" ]; then
    log "Updating existing checkout at $CAR_HOME"
    git -C "$CAR_HOME" fetch --depth 1 origin "$CAR_GIT_REF"
    git -C "$CAR_HOME" checkout "$CAR_GIT_REF"
    git -C "$CAR_HOME" reset --hard "origin/$CAR_GIT_REF"
  else
    log "Cloning $repo_url into $CAR_HOME"
    mkdir -p "$(dirname "$CAR_HOME")"
    git clone --depth 1 --branch "$CAR_GIT_REF" "$repo_url" "$CAR_HOME"
  fi
}

build_container() {
  local current_ref
  local marker_file="$CAR_HOME/.car-install-build-ref"
  current_ref="$(git -C "$CAR_HOME" rev-parse HEAD)"

  if [ "$CAR_FORCE" != "1" ] && docker image inspect "$CAR_DOCKER_IMAGE" >/dev/null 2>&1; then
    if [ -f "$marker_file" ] && [ "$(cat "$marker_file")" = "$current_ref" ]; then
      log "Skipping container build; image and git ref are unchanged"
      return
    fi
  fi

  log "Building car container image"
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$CAR_HOME/docker-compose.yml" build car
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$CAR_HOME/docker-compose.yml" build car
  else
    echo "Docker Compose is required but was not found." >&2
    exit 1
  fi

  printf '%s' "$current_ref" >"$marker_file"
}

create_or_reuse_tools_venv() {
  require_cmd python3

  if [ -x "$CAR_TOOLS_PYTHON" ]; then
    log "Using existing tools venv at $CAR_TOOLS_VENV"
    return
  fi

  log "Creating tools venv at $CAR_TOOLS_VENV"
  python3 -m venv "$CAR_TOOLS_VENV"
}

ensure_python_package_in_tools_venv() {
  local package_name="$1"
  local import_name="$2"

  if [ "$CAR_FORCE" = "1" ]; then
    log "Installing/updating $package_name in tools venv (--force)"
    "$CAR_TOOLS_PIP" install --upgrade "$package_name"
    return
  fi

  if "$CAR_TOOLS_PYTHON" -c "import $import_name" >/dev/null 2>&1; then
    log "$package_name already installed in tools venv"
    return
  fi

  log "Installing $package_name in tools venv"
  "$CAR_TOOLS_PIP" install "$package_name"
}

ensure_car_host_cli_installed() {
  if [ "$CAR_FORCE" = "1" ] || [ ! -x "$CAR_TOOLS_CAR" ]; then
    log "Installing car host CLI in tools venv"
    "$CAR_TOOLS_PIP" install --editable "$CAR_HOME"
    return
  fi

  log "car host CLI already installed in tools venv"
}

ensure_host_tools() {
  create_or_reuse_tools_venv
  ensure_python_package_in_tools_venv "$CAR_MATTSTASH_PACKAGE" mattstash

  if [ "$CAR_INSTALL_MODE" = "venv" ]; then
    ensure_car_host_cli_installed
  fi
}

copilot_extension_installed() {
  if ! command -v gh >/dev/null 2>&1; then
    return 1
  fi

  gh extension list 2>/dev/null | grep -Eiq '(^|[[:space:]])(github/)?gh-copilot([[:space:]]|$)'
}

ensure_gh_copilot_installed() {
  if command -v gh >/dev/null 2>&1 && copilot_extension_installed; then
    log "Detected GitHub CLI with Copilot extension"
    return
  fi

  require_cmd curl
  require_cmd bash

  log "Installing GitHub Copilot CLI via $CAR_COPILOT_INSTALL_URL"
  curl -fsSL "$CAR_COPILOT_INSTALL_URL" | bash
}

ensure_mattstash_initialized() {
  if "$CAR_MATTSTASH_CLI" keys >/dev/null 2>&1; then
    return 0
  fi

  if ! can_prompt; then
    warn "mattstash is not initialized and non-interactive mode is enabled"
    warn "Run manually: $CAR_MATTSTASH_CLI setup"
    return 1
  fi

  if prompt_yes_no "mattstash is not initialized. Run mattstash setup now?" "y"; then
    "$CAR_MATTSTASH_CLI" setup
    return 0
  else
    warn "Skipping mattstash setup; key storage may fail until setup is completed"
    return 1
  fi
}

persist_key_name() {
  local key_name="$1"

  python3 - "$key_name" "$CAR_MATTSTASH_CLI" <<'PY'
import json
from pathlib import Path
import sys

key_name = sys.argv[1]
mattstash_cli = sys.argv[2]
state_path = Path.home() / ".config" / "car" / "state.json"
state_path.parent.mkdir(parents=True, exist_ok=True)

data = {}
if state_path.exists():
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}

data["key_name"] = key_name
data["key_helper"] = f"{mattstash_cli} put {key_name} --value '<OPENROUTER_KEY>'"
state_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

configure_keys_wizard() {
  local do_configure="$CAR_CONFIGURE_KEYS"
  local key_name="$CAR_MATTSTASH_KEY_NAME"
  local key_value=""

  if [ "$do_configure" = "ask" ]; then
    if prompt_yes_no "Configure OpenRouter key in mattstash now?" "y"; then
      do_configure="1"
    else
      do_configure="0"
    fi
  fi

  if [ "$do_configure" != "1" ]; then
    log "Skipping key setup wizard"
    return
  fi

  if ! ensure_mattstash_initialized; then
    persist_key_name "$key_name"
    return
  fi

  if can_prompt; then
    read -r -p "mattstash key name [$key_name]: " entered_key_name </dev/tty
    if [ -n "${entered_key_name:-}" ]; then
      key_name="$entered_key_name"
    fi

    read -r -s -p "OpenRouter API key: " key_value </dev/tty
    printf '\n'
  else
    warn "Non-interactive mode cannot securely prompt for API key"
    warn "Store it later with: $CAR_MATTSTASH_CLI put $key_name --value '<OPENROUTER_KEY>'"
    persist_key_name "$key_name"
    return
  fi

  if [ -z "$key_value" ]; then
    warn "No key entered; skipping storage"
    persist_key_name "$key_name"
    return
  fi

  if "$CAR_MATTSTASH_CLI" get "$key_name" --show-password >/dev/null 2>&1; then
    if ! prompt_yes_no "Key '$key_name' already exists. Overwrite?" "n"; then
      log "Keeping existing mattstash value for $key_name"
      persist_key_name "$key_name"
      return
    fi
  fi

  "$CAR_MATTSTASH_CLI" put "$key_name" --value "$key_value" >/dev/null
  persist_key_name "$key_name"
  unset key_value
  log "Stored key in mattstash as '$key_name'"
}

configure_mattstash_profile() {
  local enabled="$CAR_ENABLE_MATTSTASH_PROFILE"

  if [ "$enabled" = "ask" ]; then
    if prompt_yes_no "Show optional mattstash Docker profile setup commands?" "y"; then
      enabled="1"
    else
      enabled="0"
    fi
  fi

  if [ "$enabled" != "1" ]; then
    return
  fi

  log "Optional mattstash profile is available in docker-compose.yml"
  log "Start it with: docker compose --profile mattstash up -d mattstash"
  log "Required env before startup: KDBX_PASSWORD and MATTSTASH_API_KEY"
}

warm_model_cache() {
  local cache_file="$HOME/.cache/car/models.json"

  if [ "$CAR_FORCE" != "1" ] && [ -s "$cache_file" ]; then
    log "Model cache already exists; skipping refresh"
    return
  fi

  log "Refreshing model cache"
  if "$CAR_WRAPPER" model refresh >/dev/null 2>&1; then
    log "Model cache refreshed"
  else
    warn "Could not refresh model cache during install"
    warn "Run: car model refresh"
  fi
}

main() {
  parse_args "$@"
  require_cmd git

  choose_install_mode

  if [ "$CAR_INSTALL_MODE" = "docker" ]; then
    require_cmd docker
  fi

  ensure_gh_copilot_installed
  clone_or_update_repo
  ensure_host_tools

  if [ "$CAR_INSTALL_MODE" = "docker" ]; then
    build_container
  fi

  write_wrapper

  append_path_export_if_missing "$HOME/.bashrc"
  append_path_export_if_missing "$HOME/.zshrc"

  configure_keys_wizard
  warm_model_cache
  configure_mattstash_profile

  log "Install complete"
  log "Try: car doctor"

  if ! printf '%s' "$PATH" | tr ':' '\n' | grep -qx "$CAR_BIN_DIR"; then
    log "Current shell PATH does not include $CAR_BIN_DIR yet"
    log "Run: export PATH=\"$CAR_BIN_DIR:\$PATH\""
  fi
}

main "$@"
