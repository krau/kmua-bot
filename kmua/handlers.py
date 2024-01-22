from kmua.callbacks import id

from pyrogram import handlers, filters

id_handler = handlers.MessageHandler(callback=id.getid, filters=filters.command("id"))
