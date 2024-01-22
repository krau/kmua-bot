from kmua.callbacks import chatinfo, help, manage

from pyrogram import handlers, filters

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

_status_refresh_handler = handlers.CallbackQueryHandler(
    callback=manage.status_refresh, filters=filters.regex("status_refresh")
)

_command_handlers = [
    _id_handler,
    _help_handler,
    _init_handler,
    _status_handler,
]

_callback_handlers = [_status_refresh_handler]

kmua_handlers = {
    0: _command_handlers,
    1: _callback_handlers,
}
