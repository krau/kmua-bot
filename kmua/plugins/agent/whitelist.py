from kmua.config import app_config


def is_chat_allowed(chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    if not app_config.agent_whitelist_mode:
        return True
    return chat_id in app_config.agent_whitelist


__all__ = ["is_chat_allowed"]
