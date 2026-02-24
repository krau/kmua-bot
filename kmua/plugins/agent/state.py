def history_key(chat_id: int, user_id: int) -> str:
    return f"message_history_with_agent:{chat_id}:{user_id}"


def waiting_key(user_id: int) -> str:
    return f"agent_waiting:{user_id}"


def bot_last_reply_key(chat_id: int) -> str:
    """存储bot在某个群组最后一条回复的信息"""
    return f"bot_last_reply:{chat_id}"


def message_follow_up_lock_key(chat_id: int, message_id: int) -> str:
    """防止对同一条消息重复处理follow-up"""
    return f"message_follow_up_lock:{chat_id}:{message_id}"


def user_messages_global_key(user_id: int) -> str:
    return f"user_messages_global:{user_id}"


def user_memory_update_key(user_id: int) -> str:
    return f"user_memory_last_update_from_cross_group:{user_id}"


def memory_key(user_id: int) -> str:
    return f"agent_user_memory:{user_id}"


def group_messages_key(chat_id: int) -> str:
    return f"group_messages:{chat_id}"


def group_memory_update_key(chat_id: int) -> str:
    return f"group_memory_last_update:{chat_id}"


def last_edited_image_key(chat_id: int, user_id: int) -> str:
    return f"agent_last_edited_image_fileid:{chat_id}:{user_id}"


def last_user_image_key(chat_id: int, user_id: int) -> str:
    return f"agent_last_user_image_fileid:{chat_id}:{user_id}"
