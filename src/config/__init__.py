from dynaconf import Dynaconf
from pathlib import Path

基础目录 = Path(__file__).parent.parent.parent

配置文件 = [
    "config.yaml",
    "config.dev.yaml",
]

配置 = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=配置文件,
    base_dir=基础目录,
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
