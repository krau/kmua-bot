from pathlib import Path

from dynaconf import Dynaconf

from ..logger import logger

_BASE_DIR = Path(__file__).resolve().parent.parent.parent

settings_files = [
    "settings.toml",
    "settings.dev.toml",
]

logger.debug(f"加载配置文件: {settings_files}")

settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=settings_files,
    environments=False,
    base_dir=_BASE_DIR,
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
