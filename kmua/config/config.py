from pathlib import Path
from typing import Any, Type, TypeVar

import pydantic
from dynaconf import Dynaconf


class _AppConfig(pydantic.BaseModel):
    token: str
    owners: list[int]
    db_url: str = "sqlite+aiosqlite:///./data/kmua.db"
    session_name: str = "kmua"
    api_id: int = 1025907
    api_hash: str = "452b0359b988148995f22ff0f4229750"
    log_retention_days: int = 30
    log_level: str = "INFO"
    lang: str = "zh-CN"

    workdir: Path = Path(__file__).resolve().parent.parent.parent / "data"
    debug: bool = False
    automigrate: bool = True
    cachedir: Path = workdir / "cache"
    avatar_cache_dir: Path = cachedir / "avatar"


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
