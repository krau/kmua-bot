from pathlib import Path
from typing import Any, Type, TypeVar

import pydantic
from dynaconf import Dynaconf


class _AppConfig(pydantic.BaseModel):
    # base config
    token: str
    owners: list[int]
    db_url: str = "sqlite+aiosqlite:///./data/kmua.db"
    session_name: str = "kmua"
    api_id: int = 1025907
    api_hash: str = "452b0359b988148995f22ff0f4229750"
    use_ipv6: bool = False
    log_retention_days: int = 30
    log_level: str = "INFO"
    lang: str = "zh-CN"

    # external services
    redis: bool = False
    redis_endpoint: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # cache
    cachettl_agent_history: int = 86400 * 3
    cachettl_chatfull: int = 86400 * 3
    cachettl_artwork_pic_file_id: int = 86400 * 7
    cachettl_sticker_fileid: int = 86400 * 7
    cachettl_history_message: int = 86400 * 3

    # manyacg
    manyacg_api_url: str = "https://api.manyacg.top/v1"
    manyacg_api_key: str
    manyacg_channel: str = "MoreACG"
    manyacg_bot: str = "kirakabot"
    manyacg_setu_cd: int = 1
    manyacg_hybrid_search: bool = True

    # agent
    agent: bool = False
    agent_model: str = "gpt-4o-mini"
    agent_provider_url: str = "https://api.openai.com/v1"
    agent_api_key: str = ""
    agent_messages_threshold: int = 20

    # experimental, maybe removed in the future
    agent_whitelist_mode: bool = False
    agent_whitelist: list[int] = []
    ############################################################################
    agent_prompt: str = r"""
System: 你是一个可爱的猫娘助手, 用户通过 Telegram Bot 与你对话, 保持可爱和耐心.

———
Internal info:
- Max length: 4096 chars
- Your Telegram username: @kmuav2bot
- Markdown: chars '_', '', '`', '\[' that are not used as boundaries MUST be escaped with '\'. 
Eg:  bold,   a \ b = ab.
"""
    ############################################################################

    # internal | debug | some other configs
    workdir: Path = Path(__file__).resolve().parent.parent.parent / "data"
    debug: bool = False
    automigrate: bool = True
    cachedir: Path = workdir / "cache"
    avatar_cache_dir: Path = cachedir / "avatar"
    avatar_expire: int = 60 * 60 * 24  # 1 day


class _InternalConfig(pydantic.BaseModel):
    db_is_sqlite: bool = False
    db_is_postgres: bool = False
    db_is_mysql: bool = False


_T = TypeVar("_T", bound=pydantic.BaseModel)


def _get_typed_config(config_class: Type[_T], settings_obj: Any = None) -> _T:
    if settings_obj is None:
        settings_obj = _settings

    config_dict = {}
    for field in config_class.__annotations__:
        if hasattr(settings_obj, field):
            config_dict[field] = getattr(settings_obj, field)
    return config_class(**config_dict)


_settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=[
        "settings.toml",
        "settings.dev.toml",
    ],
    environments=False,
)

app_config = _get_typed_config(_AppConfig)


def _get_runtime_config() -> _InternalConfig:
    cfg = _InternalConfig()
    match app_config.db_url:
        case url if url.startswith("sqlite"):
            cfg.db_is_sqlite = True
        case url if url.startswith("postgresql"):
            cfg.db_is_postgres = True
        case url if url.startswith("mysql"):
            cfg.db_is_mysql = True
        case _:
            raise ValueError(f"Unsupported database URL: {app_config.db_url}")
    return cfg


runtime_config = _get_runtime_config()

__all__ = ["app_config"]
