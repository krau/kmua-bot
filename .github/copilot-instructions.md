# kmua-bot AI Coding Agent Instructions

## Project Overview
**kmua-bot** is a feature-rich Telegram bot built with Pyrogram, featuring an AI agent system, user affection tracking, interactive games (bottle messages, waifu system), and multi-language support. The "v2" designation represents a second-generation design philosophy, not semantic versioning—expect breaking changes.

## Architecture

### Core Structure
- **Entry Point**: `kmua/__main__.py` initializes the Pyrogram client, sets bot commands, and starts scheduled jobs
- **Bot Client**: `kmua/bot/client.py` creates the Pyrogram client with plugin auto-discovery from `kmua/plugins/`
- **Plugin System**: All feature handlers in `kmua/plugins/` are auto-loaded via Pyrogram's plugin system
  - Handlers use decorators: `@Client.on_message()`, `@Client.on_callback_query()`, etc.
  - Group numbers control execution order (lower = earlier): `group=0` for commands, `group=100` for background tasks

### Configuration System
- **Dynaconf**: Configuration loaded from `settings.toml` (user config) and `settings.dev.toml` (dev overrides)
- **Config Model**: `kmua/config/__init__.py` defines `_AppConfig` with Pydantic validation
- Access via `from kmua.config import app_config`
- Key configs: `token`, `owners`, `db_url`, `agent_*`, `manyacg_*`, `redis_*`

### Database Layer
- **SQLAlchemy async**: Database models in `kmua/database/models.py`
- **Session Management**: Use `@with_session` decorator on functions that need DB access
  ```python
  @with_session
  async def my_function(session: AsyncSession, user_id: int):
      # session is automatically provided and managed
      result = await session.execute(select(UserData).where(UserData.id == user_id))
  ```
- **Migrations**: Alembic migrations in `alembic/versions/` (run `alembic upgrade head`)
- **Key Models**: `UserData`, `ChatData`, `UserChatAssociation`, `Bottle`, `Quote`, `Gift`
- **User/Chat Config**: JSON fields with dataclass wrappers (`UserConfig`, `ChatConfig`)

### Internationalization (i18n)
- **Custom YAML-based**: `kmua/i18n/__init__.py` loads translations from `kmua/i18n/locales/{locale}/`
- Access translations: `i18n.t("key.path", locale="zh-CN")` with dot-notation keys
- Translations organized by feature: `bot.yml`, `log.yml`, `bot.cmd.yml`, etc.
- Supports placeholders: `i18n.t("log.welcome", locale=lang).format(name=name, id=id)`

## Key Patterns & Conventions

### Plugin Handler Structure
```python
from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.command("mycommand"), group=0)
async def my_handler(client: Client, message: Message):
    # Handler logic here
    await message.reply_text("Response")
```

### AI Agent System (pydantic-ai)
- **Location**: `kmua/plugins/agent/`
- **Core Agent**: `agent.py` defines the main AI agent with OpenAI-compatible models
- **Tools**: `kmua/plugins/agent/tools/` - Functions decorated with `@tool` that the agent can call
  - Tools have `prepare` functions to conditionally enable them (e.g., only in groups)
  - Examples: `get_chat_info`, `search_messages`, `schedule_message`, `send_anime_photo`
- **Context**: `ContextDeps` dataclass passes chat/user context to tools
- **Memory System**: 
  - Short-term: Message history with auto-summarization when threshold reached
  - Long-term: User memory stored in cache, updated via `memory_agent`
  - Cross-group memory: Optional feature tracking user interactions globally
- **History Processing**: `history_processor` summarizes old messages and updates user memory

### Caching Strategy
- **Redis/Memcache**: Configured via `app_config.redis`
- **Memory Cache**: `kmua/common/memory_store.py` provides `memttlcache` wrapper
- **TTL Configs**: All cache TTLs configured in `app_config.cachettl_*`
- Cache keys use prefixed patterns: `agent_history:{chat_id}:{user_id}`

### Service Integration Pattern
- **External Services**: `kmua/services/` for reusable service clients
  - `manyacg`: Image/artwork search API
  - `btts`: Bilibili text-to-speech service
  - `aniobjcut`: Anime character extraction
- Services configured via `app_config.{service}_*` settings
- Always check service enabled status before use: `if app_config.btts:`

## Development Workflows

### Running the Bot
```bash
# Using Docker (recommended)
docker-compose up -d

# Local development (requires Python 3.13)
uv sync          # Install dependencies with uv
uv run python -m kmua

# Or with plain Python after installing dependencies
python -m kmua
```

### Database Migrations
```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Configuration
1. Copy `settings.toml` and fill in `token`, `owners`, `db_url`
2. For development, use `settings.dev.toml` to override settings
3. Required: `token` (Telegram bot token), `owners` (list of admin user IDs)
4. Optional: Database defaults to SQLite, Redis for distributed caching

### Adding New Features
1. **Plugin**: Create file in `kmua/plugins/` or subdirectory
2. **Handler**: Use Pyrogram decorators with appropriate `group` number
3. **Database**: Add model to `models.py`, create migration
4. **i18n**: Add translations to `kmua/i18n/locales/{locale}/` YAML files
5. **Config**: Add settings to `_AppConfig` in `kmua/config/__init__.py`

### Common Utilities
- **Message Links**: `common.utils.get_msg_link(message)` / `parse_msg_link(link)`
- **Probability**: `common.utils.random_chance(0.1)` for 10% chance
- **Avatar Cache**: `common.avatar.get_avatar()` handles user avatar caching
- **Telegram Methods**: `common.tgmethod` provides extended Pyrogram helpers

## Project-Specific Details

### Affection System
- Tracks bot-user relationship strength in `UserConfig.affection`
- Updated via AI agent interactions based on conversation sentiment
- Affects AI agent's personality and response style
- Histogram tracking in `database/affection.py`

### Bottle Feature
- Users "throw" messages in bottles that others can "pick" randomly
- Cross-chat message sharing system with report/destroy mechanisms
- Uses floating point IDs for privacy (see `database/bottle.py`)

### Waifu System
- Simulates "marrying" anime characters with daily interaction limits
- Uses graph visualization (graphviz) to show relationship networks
- Affection points and gift-giving mechanics

### Quote System
- Captures and stores message quotes with probability-based triggers
- Inline query support for searching and sharing quotes
- Pin-to-chat feature for memorable quotes

## Important Notes
- **Python 3.13 Required**: Project uses latest Python features
- **Breaking Changes**: Check commit history before updating
- **No Semantic Versioning**: "v2" is architectural, not version numbering
- **Plugin Order Matters**: Lower `group` numbers execute first
- **Session Decorator Required**: Always use `@with_session` for DB operations
- **i18n Keys**: Use dot notation, fallback to default locale if key missing
- **Agent Whitelist**: Optional `agent_whitelist_mode` restricts AI to specific chats

## File Organization
```
kmua/
├── __main__.py           # Entry point
├── bot/                  # Core bot setup
├── config/              # Configuration management
├── database/            # SQLAlchemy models and operations
├── i18n/                # Internationalization
├── plugins/             # Feature handlers (auto-loaded)
│   ├── agent/          # AI agent system
│   ├── gift/           # Gift mechanics
│   ├── groupmanage/    # Group administration
│   ├── inlinequery/    # Inline query handlers
│   ├── quote/          # Quote system
│   └── ...
├── services/           # External service clients
└── resources/          # Static assets (fonts, images)
```
