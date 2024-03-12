import os
import shutil
import tempfile
from math import ceil, sqrt
from typing import Any, Generator

import graphviz
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.helpers import escape_markdown

from kmua import dao
from kmua.logger import logger
from kmua.models.models import ChatData, UserData

from .user import mention_markdown_v2


def get_chat_waifu_relationships(
    chat: Chat | ChatData,
) -> Generator[tuple[int, int], None, None]:
    logger.debug(f"Get chat waifu relationships for {chat.title}<{chat.id}>")
    members = dao.get_chat_user_participated_waifu(chat)
    for member in members:
        waifu = dao.get_user_waifu_in_chat_exclude_married(member, chat)
        if waifu:
            yield (member.id, waifu.id)


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
    db_user = dao.add_user(user)
    text = f"""
是否@你: {db_user.waifu_mention}
已婚: {db_user.is_married}
已婚老婆id: {db_user.married_waifu_id}
"""
    waifus_with_chat = dao.get_user_waifus_with_chat(user)
    if not waifus_with_chat:
        text += "\n你今天还没有老婆哦"
    else:
        if len(waifus_with_chat) > 233:
            waifus_with_chat = waifus_with_chat[:233]
        text += "\n你今天的老婆们(最多显示233条):\n"
        for waifu, chat in waifus_with_chat:
            text += f"{waifu.full_name} ({chat.title})\n"
    waifus_of_with_chat = dao.get_user_waifus_of_with_chat(user)
    if not waifus_of_with_chat:
        text += "\n今天还没有人把你当老婆哦"
    else:
        if len(waifus_of_with_chat) > 233:
            waifus_of_with_chat = waifus_of_with_chat[:233]
        text += "\n你今天是以下人的老婆(最多显示233条):\n"
        for waifu_of, chat in waifus_of_with_chat:
            text += f"{waifu_of.full_name} ({chat.title})\n"
    return text


def get_marry_markup(waifu_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="好耶",
                    callback_data=f"agree_marry_waifu {waifu_id} {user_id}",
                ),
                InlineKeyboardButton(
                    text="坏耶",
                    callback_data=f"refuse_marry_waifu {waifu_id} {user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="取消",
                    callback_data=f"cancel_marry_waifu {waifu_id} {user_id}",
                ),
            ],
        ]
    )


def get_waifu_text(waifu: User | UserData, is_got_waifu: bool) -> str:
    return (
        (
            rf"你今天已经抽过老婆了\! {mention_markdown_v2(waifu)} 是你今天的老婆\!"
            if is_got_waifu
            else rf"你今天的群幼老婆是 {mention_markdown_v2(waifu)} \!"
        )
        if waifu.waifu_mention
        else (
            rf"你今天已经抽过老婆了\! {escape_markdown(waifu.full_name,2)} 是你今天的老婆\!"
            if is_got_waifu
            else rf"你今天的群幼老婆是 {escape_markdown(waifu.full_name,2)} \!"
        )
    )


def render_waifu_graph(
    relationships: Generator[tuple[int, int], None, None],
    user_info: Generator[dict[str, Any], None, None],
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
        format="webp",
    )

    tempdir = tempfile.mkdtemp()

    try:
        # Create nodes
        has_avatar = set()
        for user in user_info:
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
            with open(avatar_path, "wb") as avatar_file:
                avatar_file.write(avatar)

            with dot.subgraph(name=f"cluster_{user_id}") as subgraph:
                # Set the attributes for the subgraph
                subgraph.attr(label=username)
                subgraph.attr(rank="same")  # Ensure nodes are on the same rank
                subgraph.attr(labelloc="b")  # Label position at the bottom
                subgraph.attr(style="filled")

                # Create a node within the subgraph
                subgraph.node(
                    str(user_id),
                    label="",
                    shape="none",
                    image=avatar_path,
                    imagescale="true",
                )

        # Create edges
        for user_id, waifu_id in relationships:
            dot.edge(
                str(user_id),
                str(waifu_id),
                lhead=f"cluster_{waifu_id}" if waifu_id in has_avatar else "",
                ltail=f"cluster_{user_id}" if user_id in has_avatar else "",
            )

        return dot.pipe()

    finally:
        if os.path.exists(tempdir):
            shutil.rmtree(tempdir)


def get_waifu_markup(
    waifu: User | UserData, user: User | UserData
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="remove",
                    callback_data=f"remove_waifu {waifu.id} {user.id}",
                ),
                InlineKeyboardButton(
                    text="marry",
                    callback_data=f"marry_waifu {waifu.id} {user.id}",
                ),
            ]
        ]
    )


def get_remove_markup(
    waifu: User | UserData, user: User | UserData
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="移除",
                    callback_data=f"remove_waifu_confirm {waifu.id} {user.id}",
                ),
                InlineKeyboardButton(
                    text="算了",
                    callback_data=f"remove_waifu_cancel {waifu.id} {user.id}",
                ),
            ]
        ]
    )
