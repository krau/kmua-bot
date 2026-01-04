import random

from pyrogram.client import Client
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery, InlineQuery, Message

from kmua import common, database, enums
from kmua.config import app_config
from kmua.logger import logger


@Client.on_message(group=-100)
async def on_m(client: Client, message: Message):
    if app_config.debug:
        logger.debug(message)
    user = message.sender_chat or message.from_user
    chat = message.chat
    if user is None or chat is None:
        return
    text = message.text or message.caption or ""
    if text.startswith(("/", "\\")):
        logger.trace(
            f"[Command][{chat.id}]({user.id}): {message.text or message.caption}"
        )
    if chat.type == ChatType.CHANNEL:
        message.stop_propagation()
    user_db = await database.upsert_user(user)
    if chat.type == ChatType.GROUP:
        message.stop_propagation()
    if chat.type in (ChatType.SUPERGROUP, ChatType.FORUM):
        chat_db = await database.upsert_chat(chat)
        await database.add_association_in_chat(chat_db, user_db, None)
        if random.uniform(0, 1) < app_config.coin_add_chance_on_message:
            coins = 16 * random.randint(1, 9)
            await database.add_user_coins(user_db.id, coins)
        if not await common.memttlcache.get(f"user:{user_db.id}:daily_coins_reset"):
            await database.add_user_coins(user_db.id, app_config.coin_daily_add_count)
            await common.memttlcache.set(
                f"user:{user_db.id}:daily_coins_reset",
                True,
                app_config.coin_daily_add_interval,
            )
        if app_config.agent and chat_db.chat_config.ai_reply:
            if (
                message.outgoing
                or message.service
                or message.automatic_forward
                or message.sticker
                or message.game
                or (
                    user.id
                    in (
                        enums.ChatID.ANONYMOUS_ADMIN,
                        enums.ChatID.SERVICE_CHAT,
                        enums.ChatID.FAKE_CHANNEL,
                    )
                )
            ):
                return
            await common.tgmethod.cache_message_object(message)


@Client.on_callback_query(group=-100)
async def on_cb(client: Client, callback_query: CallbackQuery):
    if app_config.debug:
        logger.debug(callback_query)
    user = callback_query.from_user
    if not callback_query.message:
        return
    chat = callback_query.message.chat
    if user is None or chat is None:
        return
    logger.trace(f"[CallBackButton][{chat.id}]({user.id}): {callback_query.data}")
    if chat.type in (ChatType.CHANNEL, ChatType.GROUP):
        callback_query.stop_propagation()
    user_db = await database.upsert_user(user)
    if chat.type == ChatType.GROUP:
        callback_query.stop_propagation()
    if chat.type == ChatType.SUPERGROUP:
        chat_db = await database.upsert_chat(chat)
        await database.add_association_in_chat(chat_db, user_db, None)


@Client.on_inline_query(group=-1)
async def on_iq(client: Client, inline_query: InlineQuery):
    if app_config.debug:
        logger.debug(inline_query)
    user = inline_query.from_user
    if user is None:
        return
    logger.trace(f"[InlineQuery]({user.id}): {inline_query.query}")
    await database.upsert_user(user)
