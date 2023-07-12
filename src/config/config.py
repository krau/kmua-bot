from pathlib import Path

from dynaconf import Dynaconf

from typing import Tuple
from math import sqrt

_BASE_DIR = Path(__file__).resolve().parent.parent.parent

settings_files = [
    "settings.toml",
    "settings.dev.toml",
]

settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=settings_files,
    environments=False,
    base_dir=_BASE_DIR,
)


def waifu_fig_size(amount: int) -> Tuple[int, int]:
    height = sqrt(amount) * 4
    width = sqrt(amount) * 4
    return height, width


# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
