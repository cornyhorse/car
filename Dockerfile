FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates git npm \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI and Copilot extension.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && gh extension install github/gh-copilot || true

# Install Claude Code CLI.
RUN npm install -g @anthropic-ai/claude-code 2>/dev/null || \
    echo "Claude Code CLI install skipped (non-fatal in container)"

COPY pyproject.toml README.md /workspace/
COPY src /workspace/src
COPY tests /workspace/tests
WORKDIR /workspace
RUN pip install --no-cache-dir -e .[dev]

ENTRYPOINT ["car"]
