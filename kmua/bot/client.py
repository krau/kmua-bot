from os import cpu_count
from pathlib import Path

from pyrogram.client import Client

from kmua.config import app_config


def _build_plugins_config() -> dict[str, object]:
    """Build plugin loading config.

    When agent is disabled, avoid importing any modules under `kmua.plugins.agent`
    so no agent handlers or side effects are loaded.
    """
    root = "kmua.plugins"
    if app_config.agent:
        return {"root": root}

    plugins_dir = Path(__file__).resolve().parent.parent / "plugins"
    include: list[str] = []
    for module_file in sorted(plugins_dir.rglob("*.py")):
        rel = module_file.relative_to(plugins_dir)
        if not rel.parts:
            continue
        if rel.parts[0] == "agent":
            continue
        if "__pycache__" in rel.parts:
            continue
        if module_file.stem == "__init__":
            continue
        include.append(".".join(rel.with_suffix("").parts))

    return {"root": root, "include": include}


client = Client(
    name=app_config.session_name,
    api_id=app_config.api_id,
    api_hash=app_config.api_hash,
    bot_token=app_config.token,
    workdir=app_config.workdir,
    plugins=_build_plugins_config(),
    ipv6=app_config.use_ipv6,
    sleep_threshold=300,
    max_concurrent_transmissions=min(32, cpu_count() or 0 + 4),
)
