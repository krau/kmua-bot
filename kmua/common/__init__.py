import html

from pyrogram.types import Chat, User

from kmua import database


async def mention_html(chat: User | Chat) -> str:
    db_user = await database.upsert_user(chat)
    if not db_user.is_real_user and db_user.username is not None:
        return f"<a href='https://t.me/{db_user.username}'>{html.escape(db_user.full_name)}</a>"
    return f"<a href='tg://user?id={chat.id}'>{html.escape(chat.full_name)}</a>"
