import random
from io import BytesIO

import httpx
from pyrogram import Client
from pyrogram.enums import ChatAction
from pyrogram.types import Chat, Message, User

from kmua import common, dao
from kmua.logger import logger


async def quote(client: Client, message: Message):
    """
    响应 /q 命令
    此功能不会在私聊中被调用, 已由 filters 过滤
    """
    user = message.sender_chat or message.from_user
    chat = message.chat
    logger.info(f"[{chat.title}]({user.username or user.full_name}): {message.text}")
    common.message_recorder(message)

    if len(message.text.split(" ")) > 1:
        return
    if not message.reply_to_message:
        await message.reply_text("请回复一条消息")
        return
    if message.topic:
        await message.reply_text("暂不支持")
        return
    quote_message = message.reply_to_message
    quote_user = quote_message.sender_chat or quote_message.from_user
    forward_from_user = quote_message.forward_from or quote_message.forward_from_chat
    if forward_from_user:
        quote_user = forward_from_user

    dao.add_user(quote_user)
    quote_message_link = common.get_message_common_link(message)
    if not quote_message_link:
        await message.reply_text("Error: 无法获取消息链接\n本群组可能不是超级群组")
        return
    if dao.get_quote_by_link(quote_message_link):
        await message.reply_text("这条消息已经在语录中了哦")
        return

    await _pin_quote_message(quote_message)

    text = ["好!", "让我康康是谁在说怪话!", "名入册焉"]

    await quote_message.reply_text(text=random.choice(text))

    quote_img_file_id = await _generate_and_sned_quote_img(
        quote_user, quote_message, client
    )
    dao.add_quote(
        chat=chat,
        user=quote_user,
        qer=user,
        message=quote_message,
        link=quote_message_link,
        img=quote_img_file_id,
    )


async def _pin_quote_message(message: Message) -> bool:
    """将消息置顶"""
    try:
        await message.pin(disable_notification=True)
        return True
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        return False


async def _generate_and_sned_quote_img(
    quote_user: User | Chat,
    quote_message: Message,
    client: Client,
) -> str | None:
    """
    生成并发送语录图片

    :param update: Update
    :param context: Context
    :param quote_message: 消息
    :param quote_user: 消息发送者
    :return: 若生成成功, 返回图片的 file_id, 否则返回 None
    """
    if not quote_message.text:
        return None
    if len(quote_message.text) > 200:
        return None
    avatar = await common.get_big_avatar(quote_user.id, client)
    if not avatar:
        return None
    await quote_message.reply_chat_action(ChatAction.UPLOAD_PHOTO)

    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(
            "http://127.0.0.1:39090/generate",
            files={
                "avatar": ("avatar.jpg", avatar, "image/jpeg"),
            },
            data={
                "text": quote_message.text,
                "name": quote_user.full_name,
            },
        )
        if resp.status_code != 200:
            return None
        quote_img = BytesIO(resp.content)
    sent_photo = await quote_message.reply_photo(photo=quote_img)
    return sent_photo.photo.file_id
