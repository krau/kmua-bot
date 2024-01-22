from telegram import Chat

from kmua import dao
from kmua.models.models import ChatData


def get_chat_info(chat: Chat | ChatData) -> str:
    db_chat = dao.add_chat(chat)
    text = f"chat_id: {db_chat.id}\n"
    text += f"title: {db_chat.title}\n\n"
    text += f"记录中共有 {len(db_chat.members)} 个成员\n"
    text += f"记录中共有 {len(db_chat.quotes)} 条语录\n\n"
    text += f"created_at: {db_chat.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += f"updated_at: {db_chat.updated_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    return text
