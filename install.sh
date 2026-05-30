#!/usr/bin/env bash
set -euo pipefail

# Public defaults for this repository; override with env vars if needed.
CAR_GITHUB_REPO="${CAR_GITHUB_REPO:-matthewkingsbury/car}"
CAR_GIT_REF="${CAR_GIT_REF:-main}"
CAR_HOME="${CAR_HOME:-$HOME/.local/share/car}"
CAR_BIN_DIR="${CAR_BIN_DIR:-$HOME/.local/bin}"
CAR_WRAPPER="$CAR_BIN_DIR/car"

log() {
  printf '[car-install] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

append_path_export_if_missing() {
  local rc_file="$1"
  local line='export PATH="$HOME/.local/bin:$PATH"'

  if [ ! -f "$rc_file" ]; then
    touch "$rc_file"
  fi

  if ! grep -Fq "$line" "$rc_file"; then
    printf '\n# Added by car installer\n%s\n' "$line" >>"$rc_file"
    log "Updated $rc_file to include ~/.local/bin in PATH"
  fi
}

write_wrapper() {
  mkdir -p "$CAR_BIN_DIR"
  cat >"$CAR_WRAPPER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

CAR_HOME="${CAR_HOME:-$HOME/.local/share/car}"

if docker compose version >/dev/null 2>&1; then
  exec docker compose -f "$CAR_HOME/docker-compose.yml" run --rm car "$@"
elif command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose -f "$CAR_HOME/docker-compose.yml" run --rm car "$@"
else
  echo "Docker Compose is required but was not found." >&2
  exit 1
fi
EOF
  chmod +x "$CAR_WRAPPER"
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
  log "Building car container image"
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$CAR_HOME/docker-compose.yml" build car
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$CAR_HOME/docker-compose.yml" build car
  else
    echo "Docker Compose is required but was not found." >&2
    exit 1
  fi
}

main() {
  require_cmd git
  require_cmd docker

  clone_or_update_repo
  build_container
  write_wrapper

  append_path_export_if_missing "$HOME/.bashrc"
  append_path_export_if_missing "$HOME/.zshrc"

  log "Install complete"
  log "Try: car doctor"

  if ! printf '%s' "$PATH" | tr ':' '\n' | grep -qx "$CAR_BIN_DIR"; then
    log "Current shell PATH does not include $CAR_BIN_DIR yet"
    log "Run: export PATH=\"$CAR_BIN_DIR:\$PATH\""
  fi
}

main "$@"
