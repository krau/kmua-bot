# ---------------------------------------------------------------- frontend build
# The Mini App panel is built here and copied into the runtime image, so the final
# image carries no Node toolchain and no node_modules.
FROM node:24-alpine AS webui
# corepack pins pnpm from package.json's "packageManager" field, so the build uses
# the same version as local development instead of whatever is newest.
RUN corepack enable
# Mirrors the repo layout, because vite.config.ts writes the bundle to
# ../kmua/webapp/dist relative to webapp/.
WORKDIR /build/webapp
# Manifests first: dependencies only re-install when they actually change.
# pnpm-workspace.yaml carries the overrides (pnpm 11): without it the
# frozen install fails with LOCKFILE_CONFIG_MISMATCH.
COPY webapp/package.json webapp/pnpm-lock.yaml webapp/.npmrc webapp/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY webapp/ ./
# vue-tsc runs as part of `build`, so a type error fails the image build.
RUN pnpm build

# ------------------------------------------------------------------ runtime image
FROM ghcr.io/astral-sh/uv:debian-slim
WORKDIR /kmua
COPY pyproject.toml uv.lock ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ make build-essential git graphviz ca-certificates ffmpeg curl \
        python3 python3-dev jq zip unzip sqlite3 wget tree nodejs npm tini && \
    uv sync --frozen --no-dev --compile-bytecode && \
    uv pip install pip && \
    apt-get purge -y --auto-remove gcc g++ make build-essential python3-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# landrun: landlock sandbox for the agent shell (pinned version).
RUN curl -fsSL -o /usr/local/bin/landrun \
      https://github.com/Zouuup/landrun/releases/download/v0.1.17/landrun-linux-amd64 \
    && chmod +x /usr/local/bin/landrun

# GitHub CLI from GitHub's official Debian repository: the agent logs in once
# under the shared shell HOME (agent_shell_shared_state_path) and stays logged
# in for every later command. Community/Debian packages are old and broken
# (see cli/cli docs/install_linux.md), hence the official repo.
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
         https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && printf 'deb [arch=%s signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main\n' \
         "$(dpkg --print-architecture)" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . .
RUN .venv/bin/python -m compileall -q -j 0 kmua
# Where the FastAPI app looks for the bundle by default.
COPY --from=webui /build/kmua/webapp/dist /kmua/kmua/webapp/dist

# Health check and Mini App panel share this port
EXPOSE 8180

ENTRYPOINT ["tini", "--", "uv", "run", "--no-sync", "python", "-m", "kmua"]
