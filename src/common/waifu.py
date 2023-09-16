from telegram import Chat, User

from ..dao.chat import get_chat_members
from ..dao.user import add_user
from ..logger import logger
from ..models.models import ChatData, UserData
from ..service.waifu import (
    get_user_waifu_in_chat_exclude_married,
    get_user_waifus_of_with_chat,
    get_user_waifus_with_chat,
)


def get_chat_waifu_relationships(
    chat: Chat | ChatData,
) -> list[tuple[int, int]]:
    relationships = []
    logger.debug(f"Get chat waifu relationships for {chat.title}<{chat.id}>")
    members = get_chat_members(chat)
    for member in members:
        waifu = get_user_waifu_in_chat_exclude_married(member, chat)
        if waifu:
            relationships.append((member.id, waifu.id))
    return relationships
           



def get_chat_waifu_info_dict(
    chat: Chat | ChatData,
) -> dict[int, int]:
    # waifu_info_dict: a dict that maps user_id to waifu_id
    logger.debug(f"Get chat waifu info dict for {chat.title}<{chat.id}>")
    waifu_info_dict = {}
    for user_id, waifu_id in get_chat_waifu_relationships(chat):
        waifu_info_dict[user_id] = waifu_id
    return waifu_info_dict


def get_user_waifu_info(user: User | UserData) -> str:
    logger.debug(f"Get user waifu info for {user.full_name}<{user.id}>")
    db_user = add_user(user)
    text = f"""
是否@你: {db_user.waifu_mention}
已婚: {db_user.is_married}
已婚老婆id: {db_user.married_waifu_id}
"""
    waifus_with_chat = get_user_waifus_with_chat(user)
    if not waifus_with_chat:
        text += "\n你今天还没有老婆哦"
    else:
        if len(waifus_with_chat) > 233:
            waifus_with_chat = waifus_with_chat[:233]
        text += "\n你今天的老婆们(最多显示233条):\n"
        for waifu, chat in waifus_with_chat:
            text += f"{waifu.full_name} ({chat.title})\n"
    waifus_of_with_chat = get_user_waifus_of_with_chat(user)
    if not waifus_of_with_chat:
        text += "\n今天还没有人把你当老婆哦"
    else:
        if len(waifus_of_with_chat) > 233:
            waifus_of_with_chat = waifus_of_with_chat[:233]
        text += "\n你今天是以下人的老婆(最多显示233条):\n"
        for waifu_of, chat in waifus_of_with_chat:
            text += f"{waifu_of.full_name} ({chat.title})\n"
    return text
