import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common
from kmua.logger import logger


async def title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name}) <title>")
    message = update.effective_message
    user = message.sender_chat if message.sender_chat else user
    user_mention = ""
    user_mention = common.mention_markdown_v2(user)
    replied_user = None
    replied_message = None
    custom_title = " ".join(context.args) if context.args else None
    user_id = user.id
    if message.reply_to_message:
        replied_message = message.reply_to_message
        replied_user = replied_message.from_user
        user_id = replied_user.id
        if not custom_title:
            custom_title = (
                replied_user.username
                if replied_user.username
                else replied_user.full_name
            )
    if not custom_title:
        custom_title = user.username if user.username else user.full_name
    title_permissions: dict = context.chat_data.get("title_permissions", {})
    try:
        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            can_manage_chat=True,
            can_change_info=title_permissions.get("can_change_info"),
            can_delete_messages=title_permissions.get("can_delete_messages"),
            can_invite_users=title_permissions.get("can_invite_users"),
            can_edit_messages=title_permissions.get("can_edit_messages"),
            can_manage_topics=title_permissions.get("can_manage_topics"),
            can_manage_video_chats=title_permissions.get("title_permissions"),
            can_pin_messages=title_permissions.get("can_pin_messages"),
            can_restrict_members=title_permissions.get("can_restrict_members"),
        )
        await context.bot.set_chat_administrator_custom_title(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            custom_title=custom_title,
        )
        if replied_message:
            text_when_have_replied_message = (
                f"{user_mention}"
                + f" 把 {replied_user.mention_markdown_v2()}"
                + f" 变成{escape_markdown(custom_title,2)} \!"
            )
        text = (
            f"好, 你现在是{escape_markdown(custom_title,2)}啦"
            if not replied_message
            else text_when_have_replied_message
        )
        # 在中英文之间加入空格
        text = re.sub(r"([a-zA-Z])([\u4e00-\u9fa5])", r"\1 \2", text)
        text = re.sub(r"([\u4e00-\u9fa5])([a-zA-Z])", r"\1 \2", text)

        sent_message = await message.reply_markdown_v2(
            text=text, disable_web_page_preview=True
        )
        logger.info(f"Bot: {sent_message.text}")
    except BadRequest as e:
        if e.message == "Not enough rights":
            text = "咱没有足够的权限"
        elif e.message == "Can't remove chat owner":
            text = "咱不能对群主使用喵"
        elif e.message == "Chat_admin_required":
            text = "咱只能更改由咱自己设置的管理员的头衔"
        elif e.message == "Can't promote self":
            text = "咱不能更改自己的头衔喵"
        else:
            text = f"失败了喵: {e.message}"
            logger.error(f"{e.message}")
        sent_message = await message.reply_text(text=text)
        logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        raise e


_title_permissions_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(
                "修改信息", callback_data="set_title_permissions can_change_info"
            ),
            InlineKeyboardButton(
                "删除信息", callback_data="set_title_permissions can_delete_messages"
            ),
        ],
        [
            InlineKeyboardButton(
                "邀请用户", callback_data="set_title_permissions can_invite_users"
            ),
            InlineKeyboardButton(
                "编辑信息", callback_data="set_title_permissions can_edit_messages"
            ),
        ],
        [
            InlineKeyboardButton(
                "管理话题", callback_data="set_title_permissions can_manage_topics"
            ),
            InlineKeyboardButton(
                "管理视频聊天",
                callback_data="set_title_permissions can_manage_video_chats",
            ),
        ],
        [
            InlineKeyboardButton(
                "置顶信息", callback_data="set_title_permissions can_pin_messages"
            ),
            InlineKeyboardButton(
                "限制成员", callback_data="set_title_permissions can_restrict_members"
            ),
        ],
    ]
)


async def set_title_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name}) <set_title_permissions>")
    message = update.effective_message
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await message.reply_text("你没有权限哦")
        return
    title_permissions = context.chat_data.get("title_permissions", {})
    text = f"""点击按钮修改 /t 命令所赋予的权限, 默认不赋予任何额外权限.
当前设置:

修改信息: {title_permissions.get("can_change_info", False)}
删除信息: {title_permissions.get("can_delete_messages", False)}
邀请用户: {title_permissions.get("can_invite_users", False)}
编辑信息: {title_permissions.get("can_edit_messages", False)}
管理话题: {title_permissions.get("can_manage_topics", False)}
视频聊天: {title_permissions.get("can_manage_video_chats", False)}
置顶信息: {title_permissions.get("can_pin_messages", False)}
限制成员: {title_permissions.get("can_restrict_members", False)}
"""
    await update.message.reply_text(
        text=text,
        reply_markup=_title_permissions_markup,
    )


async def set_title_permissions_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name}) <set_title_permissions_callback>")
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        return
    permission = update.callback_query.data.split(" ")[1]
    title_permissions = context.chat_data.get("title_permissions", {})
    if permission in title_permissions:
        title_permissions[permission] = not title_permissions[permission]
    else:
        title_permissions[permission] = True
    context.chat_data["title_permissions"] = title_permissions
    await update.callback_query.message.edit_text(
        text=f"""点击按钮修改 /t 命令所赋予的权限, 默认不赋予任何权限
当前设置:
修改信息: {title_permissions.get("can_change_info", False)}
删除信息: {title_permissions.get("can_delete_messages", False)}
邀请用户: {title_permissions.get("can_invite_users", False)}
编辑信息: {title_permissions.get("can_edit_messages", False)}
管理话题: {title_permissions.get("can_manage_topics", False)}
视频聊天: {title_permissions.get("can_manage_video_chats", False)}
置顶信息: {title_permissions.get("can_pin_messages", False)}
限制成员: {title_permissions.get("can_restrict_members", False)}
""",
        reply_markup=_title_permissions_markup,
    )
