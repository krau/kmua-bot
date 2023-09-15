from telegram import (
    Update,
)
from telegram.ext import ContextTypes
from .chatdata import chat_data_manage
from ..common.user import verify_user_can_manage_bot_in_chat, verify_user_can_manage_bot
from ..common.utils import fake_users_id
from ..logger import logger
from ..database import dao


async def manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == chat.GROUP or chat.type == chat.SUPERGROUP:
        await chat_data_manage(update, context)
        return
    # TODO: manage bot in private chat
    await chat.send_message("TODO")


async def set_bot_admin_in_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    将用户提升为bot管理员
    此功能不会在私聊中被调用, 已由 filters 过滤
    """
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name}) <promote_user_in_chat>")
    message = update.effective_message
    if not await verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await update.message.reply_text("你没有权限哦")
        return
    to_promote_user_id = None
    if replied_message := message.reply_to_message:
        if replied_message.from_user.id in fake_users_id:
            await message.reply_text("暂不支持设置该类用户为bot管理员")
            return
        to_promote_user_id = replied_message.from_user.id
    elif context.args:
        to_promote_user_id = context.args[0]
        try:
            to_promote_user_id = int(to_promote_user_id)
        except ValueError:
            await message.reply_text("请输入正确的用户ID, 或者回复一名消息")
            return
    else:
        await message.reply_text("请输入正确的用户ID, 或者回复一名消息")
        return
    db_user = dao.get_user_by_id(to_promote_user_id)
    if not db_user:
        await message.reply_text("该用户不存在")
        return
    if not dao.check_user_in_chat(db_user, chat):
        await message.reply_text("该用户不在本群")
        return
    if not db_user.is_real_user:
        await message.reply_text("暂不支持设置该类用户为bot管理员")
        return
    association = dao.get_user_association_in_chat(db_user, chat)
    association.is_bot_admin = not association.is_bot_admin
    dao.commit()
    await message.reply_text(
        f"已将{db_user.full_name}在本群的bot管理权限设置为{association.is_bot_admin}"
    )


async def set_bot_admin_globally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"{user.name} <set_bot_admin_globally>")
    if not verify_user_can_manage_bot(user):
        return
    message = update.effective_message
    if not context.args:
        await message.reply_text("请输入正确的用户ID")
        return
    to_promote_user_id = context.args[0]
    try:
        to_promote_user_id = int(to_promote_user_id)
    except ValueError:
        await message.reply_text("请输入正确的用户ID")
        return
    db_user = dao.get_user_by_id(to_promote_user_id)
    if not db_user:
        await message.reply_text("该用户不存在")
        return
    db_user.is_bot_global_admin = not db_user.is_bot_global_admin
    dao.commit()
    await message.reply_text(
        f"已将{db_user.full_name}的bot全局管理权限设置为{db_user.is_bot_global_admin}"
    )