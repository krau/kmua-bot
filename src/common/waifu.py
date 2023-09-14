from typing import Generator

from telegram import Chat

from ..database import dao
from ..database.model import ChatData


def get_chat_waifu_relationships(
    chat: Chat | ChatData,
) -> Generator[tuple[int, int], None, None]:
    # relationships: a generator that yields (int, int) for (user_id, waifu_id)
    members = dao.get_chat_members(chat)
    for member in members:
        waifu = dao.get_user_waifu_in_chat(member, chat)
        if waifu:
            yield (member.id, waifu.id)


def get_chat_waifu_info_dict(
    chat: Chat | ChatData,
) -> dict[int, int]:
    # waifu_info_dict: a dict that maps user_id to waifu_id
    waifu_info_dict = {}
    for user_id, waifu_id in get_chat_waifu_relationships(chat):
        waifu_info_dict[user_id] = waifu_id
    return waifu_info_dict
