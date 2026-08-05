# Repository Guidelines

## Project Overview

kmua-bot is a Telegram bot (Python 3.13, Pyrogram/kurigram) with an integrated admin panel: a FastAPI webapp serving a Telegram Mini App built with Vue 3 + TypeScript. The bot and panel share **one process and one asyncio event loop** (uvloop): bot client, uvicorn task, APScheduler jobs, and watchdog monitors all run together. Entry point: `python -m kmua`.

Features: group management, quotes, bottles, RSS, link parsing (coolapk/tieba/twitter/wechat), in-chat AI agent (sandboxed shell/io/tg tools), affection system, waifu, wordcloud, chat titles, gifts.

Note: "v2" in branch names is a design generation, not semver-major (README). Breaking changes can land anytime — check commit history.

## Architecture & Data Flow

- **Startup** (`kmua/__main__.py`): `uvloop.install()` → alembic migrate (if `automigrate=true`) → `db.init_db()` → `LoopLagMonitor` → `webapp_server.start()` → `client.start()` → `SessionHealthMonitor` → `idle()`. `on_start` hook: chat policies, agent code repo, `get_me`/upsert user, bot commands (hash-cached in `data/.commands_hash`), jobqueue registration. `on_stop`: jobqueue shutdown, `db.close_db()`.
- **Message flow**: Telegram update → pyrogram client → plugin handlers registered with `@Client.on_message(filters..., group=N)`. Processing order: group **-100** middleware, **-1** link parsers, **0** default commands, **1+** later handlers, **100** agent memory. Plugins are auto-discovered modules under `kmua/plugins/` (namespace package, no `__init__.py`).
- **Plugin → service → DB**: plugins call plain modules in `kmua/services/` (parse functions separated from network I/O for testability), which persist via DAOs in `kmua/database/` decorated with `@with_session`/`@with_tx` (SQLAlchemy 2.0 async, `expire_on_commit=False`). Default DB is SQLite (`data/kmua.db`); Postgres supported (runtime config flags).
- **Webapp flow**: Mini App launch → raw initData POSTed to `/api/auth/telegram` → HMAC verified (`kmua/webapp/auth.py`) → JWT (HS256, secret derived from bot token) held in memory only → role-gated routers (`system/auth/me/chats/admin`) → DAOs. SPA static mount is last, so `/api/*` never falls back to the shell. `/health` + `/ready` for liveness (503 with documented shape when bot disconnected).
- **Agent subsystem** (`kmua/plugins/agent/`): in-chat AI agent with tools — shell (landrun sandbox, `kmua/services/sandbox.py`), io (AgentFS workspaces `work://`, `kmua://` read-only, `chat://`, `memory://`), tg (Bot API mapping), web (SSRF-guarded via `kmua/common/safe_http.py`). System prompts live in `.dev-notes/prompt_new.toml` (English edition).

## Key Directories

| Path | Purpose |
|---|---|
| `kmua/` | Python core package |
| `kmua/plugins/` | Auto-discovered Telegram plugins (namespace pkg); `middlewares/`, `agent/`, `waifu/`, `quote/` subpackages |
| `kmua/services/` | Pure service modules: `link_parse.py`, `twitter.py` (FxEmbed v2), `wechat.py`, `sandbox.py`; subpackages `manyacg/`, `rss/`, `image_gen/`, `btts/`, `konatagger/` |
| `kmua/database/` | SQLAlchemy models + DAO modules (one per entity: `user`, `chat`, `quote`, `bottle`, `rss`, `gift`, `stats`, …) |
| `kmua/webapp/` | FastAPI backend: `create_app()`, `auth.py`, `deps.py` (roles), `errors.py` (ApiError + stable ErrorCode strings), `routers/`, `ratelimit.py`, `sanitize.py`, `metrics.py`, `audit.py` |
| `kmua/common/` | Shared utils: `utils.py` (spawn, is_explicit_reply), `memory_store.py`, `jobs.py` (APScheduler wrapper), `tgmethod.py`, `ops.py`, `safe_http.py`, `avatar.py` |
| `webapp/` | Vue 3 frontend (Vite, Tailwind 4, Pinia); build output → `../kmua/webapp/dist` (served by FastAPI) |
| `tests/` | pytest suite (unit + API integration tiers) |
| `alembic/` | DB migrations (`versions/`, linear chain) |
| `scripts/` | Dev helpers: `dev_server.py` (panel without Telegram), `dev_init_data.py` (signed initData) |
| `docs/` | mkdocs site (zh, Material theme); `docs/docs/*.md` content |

## Development Commands

```bash
# Python (uv)
uv sync                          # install deps (add deps via uv add; uv.lock committed)
uv run python -m kmua            # run bot + panel (uses settings.toml / settings.dev.toml)
uv run pytest                    # full backend test suite
uv run pytest tests/test_foo.py -k name -x
uv run alembic revision -m "add_x" && uv run alembic upgrade head
# ruff/pyrefly are NOT project deps: run via uvx at dev time (pyrefly.toml = all defaults)

# Frontend (pnpm, from webapp/)
pnpm install                     # frozen-lockfile in CI
pnpm dev                         # Vite on :5173, /api proxied to 127.0.0.1:8180
pnpm build                       # vue-tsc typecheck inside; dist → ../kmua/webapp/dist
pnpm typecheck / pnpm lint / pnpm lint:fix / pnpm format / pnpm test

# Frontend-only dev: scripts/dev_server.py (FastAPI panel without Telegram; /health returns 503 by design)
# then scripts/dev_init_data.py writes signed initData to webapp/.env.local as VITE_DEV_INIT_DATA
# (read only under import.meta.env.DEV; never reaches prod bundle)

# Docker
docker compose up -d             # image ghcr.io/krau/kmua-bot:v2; needs settings.toml (token + owner IDs)
```

## Code Conventions & Common Patterns

**Python**
- Async-first: all I/O functions are `async def`; tests rely on pytest-asyncio `auto` mode (no decorators).
- DB access only via `@with_session`/`@with_tx` from `kmua.database.db`; decorated functions take `session: AsyncSession | None = None` as last param. `db.py` is NOT re-exported by `kmua/database/__init__.py` — import `from kmua.database import db` or `from .db import ...`.
- Config is a pydantic singleton `app_config` (dynaconf reads `settings.toml`, `settings.dev.toml` overrides, env prefix `KMUA_`). `reload_config()` mutates in place and rejects critical field changes. Treat config as read-only in handlers.
- Background tasks: `kmua.common.utils.spawn()` (keeps strong refs, logs errors) — not bare `asyncio.create_task`.
- No DI framework: modules and module-level singletons (e.g. `kmua.bot.client`). Monkeypatching these in tests must target the import site (see Testing).
- Naming: snake_case modules/functions; DAO file per entity; plugins one logical feature per file.
- Error handling: raise domain exceptions, log via loguru; webapp API errors are `ApiError` with stable string `ErrorCode` (never leak exception internals).

**Frontend (webapp/)**
- Strict TS: `noUncheckedIndexedAccess`, `verbatimModuleSyntax`, `isolatedModules`; `@/*` alias → `src/*`; `consistent-type-imports` (inline style); `no-console` is an error (warn/error allowed).
- Prettier: printWidth 100, double quotes, semicolons, trailingComma all.
- **Every user-facing string goes through `t()`/`tError()`** — flat JSON locale files in `webapp/src/i18n/` (zh-CN default, en secondary).
- State: Pinia stores; forms use `useDirtyState` (draft-over-baseline); async views use `useAsyncData` + `StateBlock` (loading/error/empty). Small form controls: `SettingsRow`/`SettingsSection`/`TextField`/`ToggleSwitch`.
- Router: `createWebHistory`, lazy imports, kebab-case route names, `meta.requiresBotAdmin` gate.
- Telegram-native UI: native main/secondary/back buttons drive saving; native popup confirms destructive actions; theme follows Telegram `themeParams`.

## Important Files

| File | Role |
|---|---|
| `kmua/__main__.py` | Entry point; startup/on_start/on_stop orchestration |
| `kmua/config/__init__.py` | `app_config` singleton (pydantic + dynaconf) |
| `kmua/bot/client.py` | Module-level `client` singleton (pyrogram/kurigram); plugin auto-load config |
| `kmua/database/db.py` | Engine, session factory, `@with_session`/`@with_tx`, `init_db`/`migrate_db` |
| `kmua/database/models.py` | `Base` + all ORM models (UserData, ChatData, Quote, Bottle, RssFeed, …) |
| `alembic/env.py` | Reads `app_config.db_url` (alembic.ini URL unused); target = models.Base |
| `kmua/webapp/__init__.py` | `create_app(panel_enabled=...)`; health-only when panel disabled |
| `kmua/webapp/auth.py` / `deps.py` / `errors.py` | initData→JWT auth; role deps; ApiError codes |
| `settings.toml` / `settings.dev.toml` | Runtime config (gitignored; dev file overrides in dev) |
| `pyproject.toml` | Metadata, pytest/uv config, 17 forced CVE-patch `[tool.uv] override-dependencies` |
| `Dockerfile` / `docker-compose.yml` | Multi-stage image (pnpm build inside); single service, healthcheck on :8180 |
| `webapp/vite.config.ts` | Alias, outDir `../kmua/webapp/dist`, `/api` dev proxy → :8180 |
| `webapp/src/main.ts` | Boot: telegram SDK → pinia → signIn (auth before mount) → me → router |

## Runtime/Tooling Preferences

- Python **3.13.* exact** (`requires-python`, `.python-version`); package manager **uv** (`uv.lock` committed). Never remove the `[tool.uv] override-dependencies` CVE patches. Runtime deps include git sources (pilmoji, kurigram) — sync needs network.
- Node ≥ 22 (24 in CI), pnpm 11 via corepack (`packageManager` field; strict-peer-dependencies). No custom registry.
- Config env prefix `KMUA_` (e.g. `KMUA_DB_URL`, `KMUA_TOKEN`); dynaconf layers: `settings.toml` ← `settings.dev.toml`.
- Backend quality gates (ruff, pyrefly) run at dev time only — **CI has no Python job**; frontend CI (`.github/workflows/webapp.yml`) runs typecheck/lint/test/build on `webapp/**` + workflow changes.
- Docker image pushes on `v2`/`dev` branches (GHCR, amd64 only); docs deploy via mkdocs gh-deploy.
- System deps for self-host: graphviz (per `docs/docs/self-host.md`); image adds ffmpeg, sqlite3, tini.
- Panel ports: 8180 local default, **8281 on test server** (remote settings). `/health` must pass before considering a deploy good.