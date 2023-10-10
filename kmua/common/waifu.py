import os
import shutil
import tempfile
from math import ceil, sqrt

import graphviz
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.helpers import escape_markdown

import kmua.dao as dao
from kmua.logger import logger
from kmua.models import ChatData, UserData


def get_chat_waifu_relationships(
    chat: Chat | ChatData,
) -> list[tuple[int, int]]:
    relationships = []
    logger.debug(f"Get chat waifu relationships for {chat.title}<{chat.id}>")
    members = dao.get_chat_members(chat)
    for member in members:
        waifu = dao.get_user_waifu_in_chat_exclude_married(member, chat)
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
            f"你今天已经抽过老婆了\! [{escape_markdown(waifu.full_name,2)}](tg://user?id={waifu.id}) 是你今天的老婆\!"  # noqa: E501
            if is_got_waifu
            else f"你今天的群幼老婆是 [{escape_markdown(waifu.full_name,2)}](tg://user?id={waifu.id}) \!"  # noqa: E501
        )
        if waifu.waifu_mention
        else (
            f"你今天已经抽过老婆了\! {escape_markdown(waifu.full_name,2)} 是你今天的老婆\!"  # noqa: E501
            if is_got_waifu
            else f"你今天的群幼老婆是 {escape_markdown(waifu.full_name,2)} \!"
        )
    )


def render_waifu_graph(
    relationships: list[tuple[int, int]],
    user_info: dict,
) -> bytes:
    dpi = max(150, ceil(5 * sqrt(len(user_info) / 3)) * 20)
    dot = graphviz.Digraph(
        graph_attr={
            "dpi": str(dpi),
            "beautify": "true",
        },
        format="webp",
    )

    tempdir = tempfile.mkdtemp()

    try:
        # Create nodes
        for user_id, info in user_info.items():
            username = info.get("username")
            username = (
                username[:6] + "..." if username and len(username) > 6 else username
            )
            if not info.get("avatar"):
                dot.node(str(user_id), label=username)
                continue
            avatar = info["avatar"]
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
            dot.edge(str(user_id), str(waifu_id))

        return dot.pipe()

    except Exception:
        raise
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
