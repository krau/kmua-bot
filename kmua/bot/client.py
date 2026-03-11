from os import cpu_count

from pyrogram.client import Client

from kmua.config import app_config

client = Client(
    name=app_config.session_name,
    api_id=app_config.api_id,
    api_hash=app_config.api_hash,
    bot_token=app_config.token,
    workdir=app_config.workdir,
    plugins={"root": "kmua.plugins"},
    ipv6=app_config.use_ipv6,
    sleep_threshold=300,
    max_concurrent_transmissions=min(32, cpu_count() or 0 + 4),
)
