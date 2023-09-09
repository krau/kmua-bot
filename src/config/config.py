from pathlib import Path

from dynaconf import Dynaconf

_BASE_DIR = Path(__file__).resolve().parent.parent.parent

avatars_dir = Path(f"{Path(__file__).resolve().parent.parent.parent}/data/avatars")

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

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
