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


command_handlers = [_id_handler, _help_handler, _init_handler]
