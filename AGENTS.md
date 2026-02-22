# AGENTS.md

Guidelines for AI coding agents working on the kmua-bot codebase.

## Project Overview

kmua-bot is a Telegram bot built with Python 3.13, using Kurigram/Pyrogram, SQLAlchemy 2.0 async with Alembic, Dynaconf with Pydantic validation, Loguru, and uv as package manager.

## Build/Lint/Test Commands

```bash
uv sync                                          # Install dependencies
uv run python -m kmua                            # Run the bot
uv run ruff check .                              # Lint check (rules: F, UP, I)
uv run ruff check . --fix                        # Auto-fix lint issues
uv run ruff format .                             # Format code
uv run alembic upgrade head                      # Database migration
uv run python test_quote_search.py               # Run a single test file
uv run python -c "from test_x import test_y; test_y()"  # Run specific test
```

## Code Style Guidelines

### Imports

Standard library first, third-party second, local last:

```python
import hashlib
from pathlib import Path

import pyrogram
from pyrogram.client import Client
from sqlalchemy import String

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
```

### Type Hints (Python 3.13+)

```python
def get_items() -> list[str]:
    pass

def get_user(id: int) -> UserData | None:
    pass

from typing import ParamSpec, TypeVar
P = ParamSpec("P")
T = TypeVar("T")

def with_session[**P, T](func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    pass
```

### Naming Conventions

- Variables/Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`
- Database models: `TableName` (e.g., `UserData`, `ChatData`)

### Async Patterns

All database operations are async:

```python
@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionFactory() as ss:
        try:
            yield ss
            await ss.commit()
        except Exception as e:
            await ss.rollback()
            raise
```

### Pyrogram Handlers

```python
from pyrogram import filters
from pyrogram.client import Client
from pyrogram.types import Message

@Client.on_message(filters.command("start") & filters.private, group=0)
async def start(client: Client, message: Message):
    chat_config = await database.get_chat_config(message.chat)
    lang = chat_config.lang
    await message.reply(i18n.t("bot.msg.private_start", locale=lang))

@Client.on_callback_query(filters.regex(r"^delete_message$"))
async def delete_message(client: Client, callback_query: CallbackQuery):
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.error(f"Failed: {e}")
```

### Database Models (SQLAlchemy 2.0)

```python
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, BigInteger

class UserData(Base):
    __tablename__ = "user_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    
    quotes: Mapped[list["Quote"]] = relationship(
        "Quote", back_populates="user", lazy="noload"
    )
```

### Error Handling

```python
from kmua.logger import logger

try:
    await some_operation()
except Exception as e:
    logger.exception(f"Operation failed: {e}")
    raise

try:
    await message.delete()
except Exception as e:
    logger.error(f"Failed: {e.__class__.__name__} - {e}")
```

### Configuration

```python
from kmua.config import app_config, runtime_config

if app_config.debug:
    print("Debug mode enabled")

if runtime_config.db_is_postgres:
    pass  # PostgreSQL-specific logic
```

### Internationalization

```python
from kmua import i18n

text = i18n.t("bot.msg.welcome", locale=lang)
text = i18n.t("bot.msg.greet", locale=lang).format(name=user.full_name)
text = i18n.trl("bot.msg.random_greeting", locale=lang)  # Random from list
```

### Pydantic Models

```python
import pydantic

class _AppConfig(pydantic.BaseModel):
    token: str
    owners: list[int]
    debug: bool = False
    db_url: str = "sqlite+aiosqlite:///./data/kmua.db"
```

## Project Structure

```
kmua-bot/
├── kmua/
│   ├── __main__.py      # Entry point
│   ├── config/          # Configuration (Dynaconf + Pydantic)
│   ├── database/        # SQLAlchemy models and operations
│   ├── plugins/         # Bot command handlers
│   ├── common/          # Shared utilities
│   ├── i18n/            # Internationalization
│   ├── logger/          # Logging setup
│   ├── bot/             # Bot client and jobs
│   └── services/        # External service integrations
├── alembic/             # Database migrations
├── settings.toml        # Production config
├── settings.dev.toml    # Development config (gitignored)
└── pyproject.toml       # Project dependencies
```

## Important Notes

- **No comments in code** unless explicitly requested
- All database operations are async
- Use `from kmua.logger import logger` for logging
- Config values come from `settings.toml` or `settings.dev.toml`
- i18n keys are in `kmua/i18n/locales/` YAML files
- Database migrations go in `alembic/versions/`
