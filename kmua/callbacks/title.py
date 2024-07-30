import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common, dao
from kmua.logger import logger


async def title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    获取头衔|互赠头衔

    :param update: Update
    :param context: Context
    :raises e: Exception when unknown error
    """
    chat = update.effective_chat
    message = update.effective_message
    user = message.sender_chat or message.from_user
    logger.info(f"[{chat.title}]({user}) <title>")
    target_user = user
    if target_message := message.reply_to_message:
        target_user = target_message.from_user
    custom_title = (
        " ".join(context.args)
        if context.args
        else target_user.username or target_user.full_name
    )
    title_permissions: dict = dao.get_chat_title_permissions(chat)
    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=target_user.id,
            can_manage_chat=True,
            can_change_info=title_permissions.get("can_change_info"),
            can_delete_messages=title_permissions.get("can_delete_messages"),
            can_restrict_members=title_permissions.get("can_restrict_members"),
            can_invite_users=title_permissions.get("can_invite_users"),
            can_pin_messages=title_permissions.get("can_pin_messages"),
            can_post_stories=title_permissions.get("can_post_stories"),
            can_edit_stories=title_permissions.get("can_edit_stories"),
            can_delete_stories=title_permissions.get("can_delete_stories"),
            can_manage_video_chats=title_permissions.get("can_manage_video_chats"),
        )
        await context.bot.set_chat_administrator_custom_title(
            chat_id=chat.id,
            user_id=target_user.id,
            custom_title=custom_title,
        )
        text = f"好, 你现在是{escape_markdown(custom_title,2)}啦"
        if message.reply_to_message:
            text = (
                f"{common.mention_markdown_v2(user)}"
                + f" 把 {common.mention_markdown_v2(target_user)}"
                + rf" 变成{escape_markdown(custom_title, 2)} \!"
            )
        text = re.sub(r"([a-zA-Z])([\u4e00-\u9fa5])", r"\1 \2", text)
        text = re.sub(r"([\u4e00-\u9fa5])([a-zA-Z])", r"\1 \2", text)

        sent_message = await message.reply_markdown_v2(
            text=text, disable_web_page_preview=True
        )
        logger.info(f"Bot: {sent_message.text}")
    except BadRequest as e:
        match e.message:
            case "Not enough rights":
                text = "咱没有足够的权限"
            case "Can't remove chat owner":
                text = "咱不能对群主使用喵"
            case "Chat_admin_required":
                text = "咱只能更改由咱自己设置的管理员的头衔"
            case "Can't promote self":
                text = "咱不能更改自己的头衔喵"
            case "Invalid user_id specified":
                text = "不能给频道身份设置头衔"
            case _:
                text = f"失败了喵: {e.message}"
                logger.error(f"{e.message}")
        sent_message = await message.reply_text(text=text)
        logger.info(f"Bot: {sent_message.text}")


_title_permissions_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(
                "修改信息", callback_data="set_title_permissions can_change_info"
            ),
            InlineKeyboardButton(
                "删除消息", callback_data="set_title_permissions can_delete_messages"
            ),
            InlineKeyboardButton(
                "封禁用户", callback_data="set_title_permissions can_restrict_members"
            ),
        ],
        [
            InlineKeyboardButton(
                "邀请用户", callback_data="set_title_permissions can_invite_users"
            ),
            InlineKeyboardButton(
                "置顶消息", callback_data="set_title_permissions can_pin_messages"
            ),
            InlineKeyboardButton(
                "管理视频聊天",
                callback_data="set_title_permissions can_manage_video_chats",
            ),
        ],
        [
            InlineKeyboardButton(
                "发布动态", callback_data="set_title_permissions can_post_stories"
            ),
            InlineKeyboardButton(
                "编辑动态", callback_data="set_title_permissions can_edit_stories"
            ),
            InlineKeyboardButton(
                "删除动态", callback_data="set_title_permissions can_delete_stories"
            ),
        ],
    ]
)


async def set_title_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    设置 /t 命令所赋予的权限

    :param update: Update
    :param context: Context
    """
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name}) <set_title_permissions>")
    message = update.effective_message
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await message.reply_text("你没有权限哦")
        return
    title_permissions = dao.get_chat_title_permissions(chat)
    await message.reply_text(
        text=_get_permissions_text(title_permissions),
        reply_markup=_title_permissions_markup,
    )


async def set_title_permissions_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    设置 /t 命令所赋予的权限(callback query)

    :param update: Update
    :param context: Context
    """
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name}) <set_title_permissions_callback>")
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        return
    permission = update.callback_query.data.split(" ")[1]
    title_permissions = dao.get_chat_title_permissions(chat)
    data = {
        "can_change_info": title_permissions.get("can_change_info", False),
        "can_delete_messages": title_permissions.get("can_delete_messages", False),
        "can_restrict_members": title_permissions.get("can_restrict_members", False),
        "can_invite_users": title_permissions.get("can_invite_users", False),
        "can_pin_messages": title_permissions.get("can_pin_messages", False),
        "can_manage_video_chats": title_permissions.get(
            "can_manage_video_chats", False
        ),
        "can_post_stories": title_permissions.get("can_post_stories", False),
        "can_edit_stories": title_permissions.get("can_edit_stories", False),
        "can_delete_stories": title_permissions.get("can_delete_stories", False),
    }
    if permission in data:
        data[permission] = not data[permission]
    dao.update_chat_title_permissions(chat, data)
    await update.callback_query.message.edit_text(
        text=_get_permissions_text(data),
        reply_markup=_title_permissions_markup,
    )


def _get_permissions_text(permissions: dict[str, bool]) -> str:
    return f"""点击按钮修改 /t 命令所赋予的权限, 默认不赋予任何额外权限
当前设置:

修改信息: {permissions.get("can_change_info", False)}
删除消息: {permissions.get("can_delete_messages", False)}
封禁用户: {permissions.get("can_restrict_members", False)}
邀请用户: {permissions.get("can_invite_users", False)}
置顶消息: {permissions.get("can_pin_messages", False)}
管理视频聊天: {permissions.get("can_manage_video_chats", False)}
发布动态: {permissions.get("can_post_stories", False)}
编辑动态: {permissions.get("can_edit_stories", False)}
删除动态: {permissions.get("can_delete_stories", False)}
"""
