"""Whether the agent may act in a given chat.

`is_chat_allowed` is called from roughly twenty places across the agent, including
message filters that cannot await, so it must stay synchronous. The authoritative
value is the `agent_enabled` flag in each chat's policy row (editable from the panel);
this module reads the in-memory mirror that every write to that table updates.

The mirror is loaded once at startup. Until it is, this falls back to the config list,
so a message arriving during initialisation is judged by the same rule the deployment
was configured with rather than being refused outright.
"""

from kmua.config import app_config
from kmua.database.chat_policy import agent_enabled_cache


def is_chat_allowed(chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    if not app_config.agent_whitelist_mode:
        return True

    cache = agent_enabled_cache()
    if cache is None:
        # Not loaded yet: fall back to the config list rather than denying every
        # chat during the startup window.
        return chat_id in app_config.agent_whitelist
    return chat_id in cache


__all__ = ["is_chat_allowed"]
