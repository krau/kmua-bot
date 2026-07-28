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
COPY webapp/package.json webapp/pnpm-lock.yaml webapp/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY webapp/ ./
# vue-tsc runs as part of `build`, so a type error fails the image build.
RUN pnpm build

# ------------------------------------------------------------------ runtime image
FROM ghcr.io/astral-sh/uv:debian-slim
WORKDIR /kmua
COPY pyproject.toml uv.lock ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ make build-essential git graphviz ca-certificates ffmpeg curl && \
    uv sync --frozen --no-dev && \
    uv pip install pip && \
    apt-get purge -y --auto-remove gcc g++ make build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
COPY . .
# Where the FastAPI app looks for the bundle by default.
COPY --from=webui /build/kmua/webapp/dist /kmua/kmua/webapp/dist

# Health check and Mini App panel share this port
EXPOSE 8180

ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "kmua"]
