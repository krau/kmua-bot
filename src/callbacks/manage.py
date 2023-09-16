from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from ..common.user import (
    download_big_avatar,
    fake_users_id,
    verify_user_can_manage_bot,
    verify_user_can_manage_bot_in_chat,
)
from .jobs import refresh_waifu_data
from ..dao.association import get_association_in_chat_by_user
from ..dao.db import db
from ..dao.user import get_user_by_id
from ..logger import logger
from ..service.user import check_user_in_chat
from .chatdata import chat_data_manage

_manage_markup = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Refresh bot info", callback_data="bot_data_refresh")]]
)


async def manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == chat.GROUP or chat.type == chat.SUPERGROUP:
        await chat_data_manage(update, context)
        return
    # TODO: manage bot in private chat
    if not verify_user_can_manage_bot(update.effective_user):
        return
    if context.bot_data.get("lock_manage_bot", False):
        await chat.send_message("Locked")
        return
    await chat.send_message("TODO...", reply_markup=_manage_markup)


async def bot_data_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if context.bot_data.get("lock_manage_bot", False):
        await chat.send_message("Locked")
        return
    context.bot_data["lock_manage_bot"] = True
    query = update.callback_query
    try:
        await query.answer("正在刷新 bot 数据...")
        db_bot_user = get_user_by_id(context.bot.id)
        avatar = await download_big_avatar(context.bot.id, context)
        db_bot_user.avatar_big_blob = avatar
        sent_message = await chat.send_photo(
            photo=avatar,
            caption="此消息用于获取 bot 头像缓存 id",
        )
        db_bot_user.avatar_big_id = sent_message.photo[-1].file_id
        db.commit()
        await sent_message.delete()
        await query.edit_message_text("刷新完成")
    finally:
        context.bot_data["lock_manage_bot"] = False


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
    db_user = get_user_by_id(to_promote_user_id)
    if not db_user:
        await message.reply_text("该用户不存在")
        return
    if not check_user_in_chat(db_user, chat):
        await message.reply_text("该用户不在本群")
        return
    if not db_user.is_real_user:
        await message.reply_text("暂不支持设置该类用户为bot管理员")
        return
    association = get_association_in_chat_by_user(chat, db_user)
    association.is_bot_admin = not association.is_bot_admin
    db.commit()
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
    db_user = get_user_by_id(to_promote_user_id)
    if not db_user:
        await message.reply_text("该用户不存在")
        return
    db_user.is_bot_global_admin = not db_user.is_bot_global_admin
    db.commit()
    await message.reply_text(
        f"已将{db_user.full_name}的bot全局管理权限设置为{db_user.is_bot_global_admin}"
    )


async def leave_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"[{user.name}] <leave_chat>")
    if not verify_user_can_manage_bot(user):
        return
    chat = update.effective_chat
    if chat.type == chat.GROUP or chat.type == chat.SUPERGROUP:
        await context.bot.leave_chat(chat.id)
        return
    if not context.args:
        await update.message.reply_text("请输入正确的群组ID")
        return
    to_leave_chat_id = context.args[0]
    try:
        to_leave_chat_id = int(to_leave_chat_id)
    except ValueError:
        await update.message.reply_text("请输入正确的群组ID")
        return
    try:
        if await context.bot.leave_chat(to_leave_chat_id):
            await update.message.reply_text("已离开群组")
        else:
            await update.message.reply_text("离开群组失败")
    except Exception as e:
        await update.message.reply_text(f"离开群组失败: {e}")


async def refresh_waifu_data_manually(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    if not verify_user_can_manage_bot(user):
        return
    await update.effective_message.reply_text("3s 后刷新 waifu_data")
    context.job_queue.run_once(refresh_waifu_data, 3)