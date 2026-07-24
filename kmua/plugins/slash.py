import html
import random
import re

from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType, ParseMode
from pyrogram.types import LinkPreviewOptions, Message

from kmua import common, database
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config


def _strip_trigger_prefix(text: str) -> str:
    return text.lstrip("$/\\")


async def slash_fliter_func(_, __, message: Message) -> bool:
    if not message.text:
        return False
    if len(message.text) <= 1:
        return False
    if (
        message.entities is not None
        and message.entities[0].type == MessageEntityType.BOT_COMMAND
    ):
        return False
    if message.text.startswith("/") or message.text.startswith("\\"):
        return True
    return False


slash_fliter = filters.create(slash_fliter_func)


@Client.on_message(slash_fliter, group=0)
async def slash(client: Client, message: Message):
    if not message.text:
        return
    if message.text.startswith("/"):
        if not message.text.startswith("//"):
            if re.match(r"^/[a-zA-Z0-9]+", message.text):
                return
    cmd1 = ""
    cmd2 = ""
    text = ""
    this_user = message.sender_chat or message.from_user
    this_mention = await common.mention_html(this_user)
    replied_user = None
    replied_mention = ""
    if is_explicit_reply(message) and message.reply_to_message:
        reply_to_message = message.reply_to_message
        replied_user = reply_to_message.sender_chat or reply_to_message.from_user
        if replied_user:
            replied_mention = await common.mention_html(replied_user)
    is_reverse = (
        False
        if message.text.startswith("/")
        else True
        if message.text.startswith("\\")
        else False
    )
    is_one_cmd = len(message.text.split(" ")) == 1
    cmd1 = html.escape(_strip_trigger_prefix(message.text.split(" ")[0][1:]))
    if not cmd1:
        return
    if not is_one_cmd:
        # TODO: i18n
        cmd2 = html.escape(" ".join(message.text.split(" ")[1:]))
        text = (
            (
                f"{replied_mention} {cmd1} {this_mention} {cmd2} !"
                if replied_user
                else f"{this_mention} {cmd1}自己{cmd2} !"
            )
            if is_reverse
            else (
                f"{this_mention} {cmd1} {replied_mention} {cmd2} !"
                if replied_user
                else f"{this_mention} {cmd1}自己{cmd2} !"
            )
        )
    else:
        text = (
            (
                f"{this_mention} 被 {replied_mention} {cmd1}了 !"
                if replied_user
                else f"{this_mention} 被自己{cmd1}了 !"
            )
            if is_reverse
            else (
                f"{this_mention} {cmd1}了 {replied_mention} !"
                if replied_user
                else f"{this_mention} {cmd1}了自己 !"
            )
        )
    # 在中英文之间加空格
    text = re.sub(r"([a-zA-Z0-9])([\u4e00-\u9fa5])", r"\1 \2", text)
    text = re.sub(r"([\u4e00-\u9fa5])([a-zA-Z0-9])", r"\1 \2", text)
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    if random.uniform(0, 1) < app_config.coin_add_chance_on_slash:
        coins = 16 * random.randint(1, 4)
        await database.add_user_coins(this_user.id, coins)
    if replied_user:
        if random.uniform(0, 1) < app_config.coin_add_chance_on_be_slash:
            coins = 16 * random.randint(1, 4)
            await database.add_user_coins(replied_user.id, coins)
