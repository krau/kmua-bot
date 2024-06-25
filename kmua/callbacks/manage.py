import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.config import settings
from kmua.logger import logger

from .chatdata import chat_data_manage
from .jobs import clean_data

_manage_markup = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Refresh bot info", callback_data="bot_data_refresh")]]
)


async def manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in (chat.GROUP, chat.SUPERGROUP):
        await chat_data_manage(update, context)
        return
    if not common.verify_user_can_manage_bot(update.effective_user):
        return
    if context.bot_data.get("lock_manage_bot", False):
        await chat.send_message("Locked")
        return
    text = """
/set_bot_admin <user_id> - 将用户提升为bot管理员(全局)
/leave_chat <chat_id> - 离开群组(同时删除群组数据)
/clean_data - 手动清理数据, 并刷新抽老婆数据
/status - 查看 bot 状态
/clear_inactive_user_avatar <days> - 清理不活跃用户的头像缓存
/error_notice - 开启/关闭错误通知
"""
    await chat.send_message(text, reply_markup=_manage_markup)


async def bot_data_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if context.bot_data.get("lock_manage_bot", False):
        await chat.send_message("Locked")
        return
    context.bot_data["lock_manage_bot"] = True
    query = update.callback_query
    try:
        await query.answer("正在刷新 bot 数据...")
        db_bot_user = dao.get_user_by_id(context.bot.id)
        avatar = await common.download_big_avatar(context.bot.id, context)
        db_bot_user.avatar_big_blob = avatar
        sent_message = await chat.send_photo(
            photo=avatar,
            caption="此消息用于获取 bot 头像缓存 id",
        )
        db_bot_user.avatar_big_id = sent_message.photo[-1].file_id
        dao.commit()
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
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await update.message.reply_text("你没有权限哦")
        return
    to_promote_user_id = None
    if replied_message := message.reply_to_message:
        if replied_message.from_user.id in common.fake_users_id:
            await message.reply_text("暂不支持设置该类用户为bot管理员")
            return
        to_promote_user_id = replied_message.from_user.id
    elif context.args:
        to_promote_user_id = context.args[0]
        try:
            to_promote_user_id = int(to_promote_user_id)
        except ValueError:
            await message.reply_text("请输入正确的用户ID, 或者回复一条消息")
            return
    else:
        await message.reply_text("请输入正确的用户ID, 或者回复一条消息")
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
    association = dao.get_association_in_chat_by_user(chat, db_user)
    association.is_bot_admin = not association.is_bot_admin
    dao.commit()
    await message.reply_text(
        f"已将{db_user.full_name}在本群的bot管理权限设置为{association.is_bot_admin}"
    )


async def set_bot_admin_globally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"{user.name} <set_bot_admin_globally>")
    if not common.verify_user_can_manage_bot(user):
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


async def leave_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"[{user.name}] <leave_chat>")
    if not common.verify_user_can_manage_bot(user):
        return
    chat = update.effective_chat
    if chat.type in (chat.GROUP, chat.SUPERGROUP):
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
    dao.delete_chat_data_and_quotes(to_leave_chat_id)
    try:
        if await context.bot.leave_chat(to_leave_chat_id):
            await update.message.reply_text("已离开群组")
        else:
            await update.message.reply_text("离开群组失败")
    except Exception as e:
        await update.message.reply_text(f"离开群组失败: {e}")


async def clean_data_manually(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not common.verify_user_can_manage_bot(user):
        return
    await update.effective_message.reply_text("3s 后开始清理数据...")
    context.job_queue.run_once(clean_data, 3)


_status_markup = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Refresh", callback_data="status_refresh")]]
)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"{update.effective_user.name} <status>")
    if context.user_data.get("lock_status", False):
        return
    context.user_data["lock_status"] = True
    query = update.callback_query
    try:
        if not query:
            await update.effective_message.reply_text(
                common.get_bot_status(), reply_markup=_status_markup
            )
            return
        await query.edit_message_text(
            common.get_bot_status(), reply_markup=_status_markup
        )
    finally:
        await asyncio.sleep(1)
        context.user_data["lock_status"] = False


# 清理不活跃用户的头像缓存
async def clear_inactive_user_avatar(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    logger.info(f"{update.effective_user.name} <clear_inactive_user_avatar>")
    if not common.verify_user_can_manage_bot(update.effective_user):
        return
    if query := update.callback_query:
        days = int(query.data.split(" ")[-1])
        await query.answer("正在清理...")
        count = dao.clear_inactived_users_avatar(days)
        await query.edit_message_text(f"已清理 {count} 个用户的头像缓存")
        return
    message = update.effective_message
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            await message.reply_text("请输入正确的天数")
            return
    if days < 1:
        await message.reply_text("请输入正确的天数")
        return
    count = dao.get_inactived_users_count(days)
    _clear_inactive_user_avatar_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "清理", callback_data=f"clear_inactive_user_avatar confirm {days}"
                ),
                InlineKeyboardButton("算了", callback_data="back_home"),
            ]
        ]
    )
    await message.reply_text(
        f"共有 {count} 个在最近 {days} 天内未活跃的用户, 确定要清理吗? (请注意备份)",
        reply_markup=_clear_inactive_user_avatar_markup,
    )


async def error_notice_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.owners:
        return
    is_enabled = context.bot_data.get("error_notice", False)
    text = "已关闭" if is_enabled else "已开启"
    text += "错误通知"
    context.bot_data["error_notice"] = not is_enabled
    await update.message.reply_text(text)


async def fix_quotes(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.owners:
        return
    await update.message.reply_text("开始修复...")
    quote_count, invalid_chat_count, failed_count = dao.fix_none_chat_id_quotes()
    await update.message.reply_text(
        f"修复完成\n"
        f"共找到 {quote_count} 条没有 chat_id 的 quote\n"
        f"无效 chat_id 数量: {invalid_chat_count}\n"
        f"失败数量: {failed_count}"
    )
