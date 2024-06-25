from telegram import Update
from telegram.ext import ContextTypes, TypeHandler
from kmua import dao
from telegram.constants import ChatType, ChatID


async def store_data(update: Update, _: ContextTypes):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not user or not chat or not message:
        return
    if chat.type == ChatType.CHANNEL or user.id == ChatID.SERVICE_CHAT:
        return
    if message.sender_chat:
        user = message.sender_chat
    db_user = dao.add_user(user)
    if chat.type in (chat.GROUP, chat.SUPERGROUP):
        dao.add_chat(chat)
        dao.add_association_in_chat(chat, db_user)


store_data_handler = TypeHandler(Update, store_data)

before_middleware = [store_data_handler]
after_middleware = []
