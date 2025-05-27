from string import Template

import pyrogram

from kmua import common, database, i18n
from kmua.logger import logger


@pyrogram.Client.on_message(
    pyrogram.filters.command("greet") & pyrogram.filters.group, group=0
)
async def set_greeting_command(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    chat = message.chat
    user = message.sender_chat or message.from_user
    chat_config = await database.get_chat_config(chat.id)
    if not await common.can_user_manage_bot_in_chat(user, chat):
        await message.reply(
            i18n.t("bot.msg.no_permission_group", locale=chat_config.lang)
        )
        return
    if len(message.command) < 2:
        await message.reply(i18n.t("bot.msg.greeting.usage", locale=chat_config.lang))
        return
    action = message.command[1].lower()
    match action:
        case "set":
            if len(message.command) < 3:
                await message.reply(
                    i18n.t("bot.msg.greeting.set_usage", locale=chat_config.lang)
                )
                return
            greeting_text = " ".join(message.command[2:])
            if len(greeting_text) > 1024:
                await message.reply(
                    i18n.t("bot.msg.greeting.too_long", locale=chat_config.lang)
                )
                return
            chat_config.greeting = greeting_text
            await database.update_chat_config(chat.id, chat_config)
            await message.reply(
                i18n.t("bot.msg.greeting.set_success", locale=chat_config.lang)
            )
        case "remove":
            chat_config.greeting = None
            await database.update_chat_config(chat.id, chat_config)
            await message.reply(
                i18n.t("bot.msg.greeting.remove_success", locale=chat_config.lang)
            )
        case "show":
            if chat_config.greeting is None:
                await message.reply(
                    i18n.t("bot.msg.greeting.not_set", locale=chat_config.lang)
                )
            else:
                try:
                    t = Template(chat_config.greeting)
                    greeting_text = t.safe_substitute(
                        user=user.mention(style="html"),
                        chat=chat.title,
                    )
                    await message.reply(
                        greeting_text,
                        parse_mode=pyrogram.enums.ParseMode.HTML,
                    )
                except Exception as e:
                    logger.error(
                        f"Error in greeting template: {e.__class__.__name__}:{e}"
                    )
                    await message.reply(
                        i18n.t(
                            "bot.msg.greeting.template_error", locale=chat_config.lang
                        )
                    )
        case _:
            await message.reply(
                i18n.t("bot.msg.greeting.usage", locale=chat_config.lang)
            )


@pyrogram.Client.on_message(pyrogram.filters.new_chat_members, group=1)
async def greeting_new_member(client: pyrogram.Client, message: pyrogram.types.Message):
    chat = message.chat
    db_chat = await database.get_chat_by_id(chat.id)
    chat_config = db_chat.chat_config
    if not chat_config.greeting:
        return
    new_member = message.new_chat_members[0]  # TODO: handle multiple new members
    t = Template(chat_config.greeting)
    greet_text = t.safe_substitute(
        user=new_member.mention(style="html"),
        chat=chat.title,
    )
    await message.reply(
        greet_text,
        parse_mode=pyrogram.enums.ParseMode.HTML,
    )
