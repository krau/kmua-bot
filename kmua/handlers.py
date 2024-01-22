from pyrogram import filters, handlers

from kmua.callbacks import chatinfo, help, manage, slash, quote


# Command handlers
_id_handler = handlers.MessageHandler(
    callback=chatinfo.getid, filters=filters.command("id")
)
_help_handler = handlers.MessageHandler(
    callback=help.help, filters=filters.command("help")
)
_init_handler = handlers.MessageHandler(
    callback=manage.init, filters=filters.command("init")
)
_status_handler = handlers.MessageHandler(
    callback=manage.status, filters=filters.command("status")
)
_quote_handler = handlers.MessageHandler(
    callback=quote.quote, filters=filters.command("q") & filters.group
)

# Callback handlers
_status_refresh_handler = handlers.CallbackQueryHandler(
    callback=manage.status_refresh, filters=filters.regex("status_refresh")
)

# Message handlers
_slash_handler = handlers.MessageHandler(
    callback=slash.slash, filters=filters.regex(r"^(/|\\)")
)

_command_handlers = [
    _id_handler,
    _help_handler,
    _init_handler,
    _status_handler,
    _quote_handler,
]

_callback_handlers = [
    _status_refresh_handler,
]

_message_handlers = [
    _slash_handler,
]

kmua_handlers = {
    0: _command_handlers,
    1: _message_handlers,
    2: _callback_handlers,
}
