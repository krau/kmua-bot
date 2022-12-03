import asyncio
import os
import logging
import telegram
import random
from src.bnhhsh.bnhhsh import dp
from telegram import Update
from telegram.ext import filters, MessageHandler, ApplicationBuilder, CommandHandler, ContextTypes
from src.Helper import Helper
from src.Filters import *
from src.Words import GetWords


'''初始化类'''
helper = Helper()
getWords = GetWords()

'''读取设定配置'''
config = helper.read_config('config.yml')
if config['proxy']:
    os.environ['http_proxy'] = config['proxy']
    os.environ['https_proxy'] = config['proxy']
TOKEN = config['token']
botname = config['botname']
master_id = config['master_id']
pr_nosese = config['pr_nosese']
pr_sleep = config['pr_sleep']
pr_ohayo = config['pr_ohayo']
pr_niubi = config['pr_niubi']
pr_aoligei = config['pr_aoligei']
pr_yinyu = config['pr_yinyu']


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="喵呜?")
    await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM7Y4oxOY0Tkt5D5keXXph7jFE7U7YAAqUCAAJfIulXxC0Bkai8vqwrBA')


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"干嘛喵,{botname}不会这个~"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def nosese(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if helper.random_unit(pr_nosese):
        await context.bot.send_message(chat_id=update.effective_chat.id, text='不要涩涩喵!')
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM_Y4oxreCJwFtLa1okJMS3Xz7g8UsAAmYCAAImjuhXJN6lY6dZeNUrBA')


async def ohayo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if helper.random_unit(pr_ohayo):
        text = getWords.get_ohayo()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAANBY4oyECkXjRogFHgphC4lXWyL1XQAAuADAALYtOlXJmc1qHGknScrBA')


async def wanan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if helper.random_unit(pr_sleep):
        text = getWords.get_wanan()
        stickers = ['CAACAgUAAxkBAANEY4oyf4yTWS2IwdQI85PXUX4HQCUAAtkDAAJWFLhWB5Xyu3EaZwcrBA',
                    'CAACAgUAAxkBAANGY4oyj4NN8khNgBs7GYbuUExqUzoAAk4CAALWY0lV3OnyI0c9yfArBA',
                    'CAACAgUAAxkBAANKY4oyz3UNU7mIgitsGlNhb1CqH30AAm0DAAIytehXTdZ5bv72-fkrBA',
                    'CAACAgUAAxkBAANLY4oy08mWXoE0e3pIqR0Sz-Lm7yoAAqkDAAKUIOBXFZ5cO9IPe0crBA']
        sticker = random.choice(stickers)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=sticker)


async def niubi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if helper.random_unit(pr_niubi):
        text = getWords.get_niubi()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def yinyu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if helper.random_unit(pr_yinyu):
        message = update.effective_message.text
        en = getWords.get_en(message)
        yinyu = getWords.get_yinyu(message)
        text = f'{en} 是 {yinyu} 的意思嘛?'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def re_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == master_id:
        file_id = update.message.sticker.file_id
        await context.bot.send_message(chat_id=update.effective_chat.id, text=file_id)
    else:
        if helper.random_unit(0.05):
            text = f'不要发表情包啦，{botname}还看不懂'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


def run():
    application = ApplicationBuilder().token(TOKEN).build()

    start_handler = CommandHandler('start', start)
    unknown_handler = MessageHandler(filters.COMMAND, unknown)
    setu_handler = MessageHandler(filter_setu, nosese)
    ohayo_handler = MessageHandler(filter_ohayo, ohayo)
    wanan_handler = MessageHandler(filter_sleep, wanan)
    niubi_handler = MessageHandler(filter_niubi, niubi)
    fileid_handler = MessageHandler(filters.Sticker.ALL, re_file_id)
    yinyu_handler = MessageHandler(filter_yinyu, yinyu)
    handlers = [start_handler, unknown_handler, setu_handler, ohayo_handler,
                wanan_handler, niubi_handler, fileid_handler, yinyu_handler]
    application.add_handlers(handlers)

    application.run_polling()


if __name__ == '__main__':
    run()
