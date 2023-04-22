
from dynaconf import Dynaconf
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=['settings.toml', 'settings.dev.toml'],
    environments=True,
    base_dir = BASE_DIR,
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
