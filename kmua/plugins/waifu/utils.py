import asyncio
import html
import os
from io import BytesIO
from math import ceil, sqrt
from typing import AsyncGenerator

import aiofiles
import graphviz
import pyrogram

from kmua import common, consts, database, i18n
from kmua.database.models import ChatData, UserData


def waifu_waiting_key(user_id: int, chat_id: int) -> str:
    return f"user:{user_id}:chat:{chat_id}:waifu:waiting"


def waifu_markup(
    waifu_id: int, user_id: int, lang: str
) -> pyrogram.types.InlineKeyboardMarkup:
    return pyrogram.types.InlineKeyboardMarkup(
        [
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.remove", locale=lang),
                    callback_data=f"remove_waifu {waifu_id} {user_id}",
                ),
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.marry", locale=lang),
                    callback_data=f"marry_waifu {waifu_id} {user_id}",
                ),
            ]
        ]
    )


async def waifu_text(
    waifu: UserData, is_got: bool, user: UserData | None = None, lang: str = "zh-CN"
) -> str:
    if waifu.waifu_mention or not waifu.is_real_user:
        waifu_text = await common.mention_html(waifu)
    else:
        waifu_text = html.escape(waifu.full_name)

    template_key = "bot.msg.waifu."
    if user:
        template_key += "got" if is_got else "normal"
        user_text = await common.mention_html(user)
        return i18n.t(template_key, locale=lang).format(
            user=user_text, waifu=waifu_text
        )
    else:
        template_key += "got_nouser" if is_got else "normal_nouser"
        return i18n.t(template_key, locale=lang).format(waifu=waifu_text)


async def get_waifu_for_user(
    user: UserData, chat: ChatData
) -> tuple[UserData | None, bool]:
    """get or take waifu for user in chat

    Returns:
        - UserData | None: waifu
        - bool: is_got
    """
    is_got = await database.is_setted_waifu_in_chat(user, chat)
    waifu, _ = await database.get_user_waifu_in_chat(user, chat)
    if waifu:
        return waifu, is_got
    waifu = await database.take_waifu_for_user_in_chat(user, chat)
    if not waifu:
        return None, is_got
    return waifu, is_got


def remove_markup(
    waifu_id: int, user_id: int, lang: str = "zh-CN"
) -> pyrogram.types.InlineKeyboardMarkup:
    return pyrogram.types.InlineKeyboardMarkup(
        [
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.remove_confirm", locale=lang),
                    callback_data=f"remove_waifu_confirm {waifu_id} {user_id}",
                ),
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.remove_cancel", locale=lang),
                    callback_data=f"remove_waifu_cancel {waifu_id} {user_id}",
                ),
            ]
        ]
    )


def marry_markup(
    waifu_id: int, user_id: int, lang: str = "zh-CN"
) -> pyrogram.types.InlineKeyboardMarkup:
    return pyrogram.types.InlineKeyboardMarkup(
        [
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.agree_marry_waifu", locale=lang),
                    callback_data=f"marry_waifu_agree {waifu_id} {user_id}",
                ),
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.refuse_marry_waifu", locale=lang),
                    callback_data=f"marry_waifu_refuse {waifu_id} {user_id}",
                ),
            ],
            [
                pyrogram.types.InlineKeyboardButton(
                    text=i18n.t("bot.button.waifu.cancel_marry_waifu", locale=lang),
                    callback_data=f"marry_waifu_cancel {waifu_id} {user_id}",
                )
            ],
        ]
    )


# Maybe this should be refactored ...
async def get_graph_data(
    chat_id: int,
    participate_users1: AsyncGenerator[UserData, None],
    participate_users2: AsyncGenerator[UserData, None] | None = None,
):
    db_chat = await database.get_chat_by_id(chat_id)

    async def _gen_relationship():
        async for user in participate_users1:
            waifu, _ = await database.get_user_waifu_in_chat(user, db_chat)
            if waifu:
                yield user.id, waifu.id

    if participate_users2 is None:
        participate_users2 = database.get_chat_user_participated_waifu(chat_id)

    user_data = (
        {
            "id": user.id,
            "username": user.username or f"{user.id}",
            "avatar": (
                await common.ChatAvatar(user.id).get_or_default_bytes(big=False)
            ),
        }
        async for user in participate_users2
    )
    return (
        _gen_relationship(),
        user_data,
    )


async def render_waifu_graph(
    relationships: AsyncGenerator[tuple[int, int], None],
    user_info: AsyncGenerator[dict[str, int | str | bytes], None],
    length: int = 0,
) -> bytes:
    dpi = max(150, ceil(5 * sqrt(length / 3)) * 20)
    dot = graphviz.Digraph(
        graph_attr={
            "dpi": str(dpi),
            "beautify": "true",
            "compound": "true",
            "ranksep": "1",
            "splines": "ortho",
        },
        format="pdf",
    )

    async with aiofiles.tempfile.TemporaryDirectory() as tempdir:
        has_avatar = set()
        avatar_tasks = []

        async for user in user_info:
            user_id = user["id"]
            username = user.get("username")
            username = (
                username[:6] + "..." if username and len(username) > 6 else username
            )

            if not user.get("avatar"):
                dot.node(str(user_id), label=username)
                continue

            has_avatar.add(user_id)
            avatar = user["avatar"]
            avatar_path = os.path.join(tempdir, f"{user_id}_avatar.png")

            avatar_task = _write_avatar(avatar_path, avatar)
            avatar_tasks.append((user_id, username, avatar_path, avatar_task))

        if avatar_tasks:
            await asyncio.gather(*[task for _, _, _, task in avatar_tasks])

            for user_id, username, avatar_path, _ in avatar_tasks:
                with dot.subgraph(name=f"cluster_{user_id}") as subgraph:
                    subgraph.attr(label=username)
                    subgraph.attr(rank="same")
                    subgraph.attr(labelloc="b")
                    subgraph.attr(style="filled")

                    subgraph.node(
                        str(user_id),
                        label="",
                        shape="none",
                        image=avatar_path,
                        imagescale="true",
                    )

        async for user_id, waifu_id in relationships:
            dot.edge(
                str(user_id),
                str(waifu_id),
                lhead=f"cluster_{waifu_id}" if waifu_id in has_avatar else "",
                ltail=f"cluster_{user_id}" if user_id in has_avatar else "",
            )

        result = await asyncio.to_thread(dot.pipe)
        return result


async def _write_avatar(avatar_path: str, avatar: bytes) -> None:
    async with aiofiles.open(avatar_path, "wb") as avatar_file:
        await avatar_file.write(avatar)


async def send_waifu_graph(chat_id: int, reply_to_msg_id: int, client: pyrogram.Client):
    chat_config = await database.get_chat_config(chat_id)
    if not chat_config.waifu_enabled:
        return
    participate_users = database.get_chat_user_participated_waifu(chat_id)
    participate_user_count = await database.count_chat_waifu_participants(chat_id)
    if participate_user_count < 2 or not participate_users:
        if reply_to_msg_id:
            await client.send_message(
                chat_id=chat_id,
                text=i18n.t("bot.msg.waifu.no_participate", locale=chat_config.lang),
                reply_parameters=pyrogram.types.ReplyParameters(
                    message_id=reply_to_msg_id
                ),
            )
        return
    relationships, user_info = await get_graph_data(
        chat_id, participate_users1=participate_users
    )
    image = await render_waifu_graph(relationships, user_info, participate_user_count)
    await client.send_document(
        chat_id=chat_id,
        document=BytesIO(image),
        caption=i18n.t(
            "bot.msg.waifu.graph_caption",
            locale=chat_config.lang,
        ).format(count=participate_user_count),
        file_name=f"waifu_graph{chat_id}.pdf",
        force_document=True,
        reply_parameters=(
            pyrogram.types.ReplyParameters(message_id=reply_to_msg_id)
            if reply_to_msg_id
            else None
        ),
    )
