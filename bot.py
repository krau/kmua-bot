import asyncio
import os
import logging
import telegram
import random
from datetime import datetime
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
        stickers = ['CAACAgUAAxkBAAPnY4xM4SVJj5T5plvLUc89Lra77IUAAvACAAL30uhX8lw2t4mq6GErBA',
                    'CAACAgUAAxkBAANBY4oyECkXjRogFHgphC4lXWyL1XQAAuADAALYtOlXJmc1qHGknScrBA']
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=random.choice(stickers))
    username = update.effective_user.full_name
    record = helper.sleep_recorder(mode='read',name=username)
    if record:
        sleep_time_str = record.get('time')
        sleep_time = datetime.strptime(sleep_time_str,'%Y-%m-%d %H:%M:%S')
        wake_time = datetime.strptime(datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'%Y-%m-%d %H:%M:%S')
        if wake_time > sleep_time:
            slumber_time = float(format(((wake_time-sleep_time).seconds / 3600),'.3f'))
            if  0.50<slumber_time<9.00: 
                text = f'{username}上次睡觉是在{sleep_time_str},这次一共睡了{slumber_time}小时哦~'
                await context.bot.send_message(chat_id=update.effective_chat.id,text=text)
            elif slumber_time<=0.50:
                text = f'{username}这次只睡了{slumber_time}小时，要好好休息哦~'
                await context.bot.send_message(chat_id=update.effective_chat.id,text=text)
            elif slumber_time>=9.00:
                text = f'{username}这次睡了{slumber_time}小时!!下次需要{botname}叫醒你吗~'
                await context.bot.send_message(chat_id=update.effective_chat.id,text=text)
                await context.bot.send_sticker(chat_id=update.effective_chat.id,sticker='CAACAgUAAxkBAAM_Y4oxreCJwFtLa1okJMS3Xz7g8UsAAmYCAAImjuhXJN6lY6dZeNUrBA')
        else:
            text = f'不对劲，算不出来{username}的睡眠时间呢，你可能上次睡觉的时候该不会给{botname}说的早安吧？'
            await context.bot.send_message(chat_id=update.effective_chat.id,text=text)
    else:
        text = f'{username}上次睡觉没有和{botname}说晚安哦~虽然没有很不开心就是了!'
        await context.bot.send_message(chat_id=update.effective_chat.id,text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id,sticker='CAACAgUAAxkBAAM_Y4oxreCJwFtLa1okJMS3Xz7g8UsAAmYCAAImjuhXJN6lY6dZeNUrBA')



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
    username = update.effective_user.full_name
    record = helper.sleep_recorder(
        mode='write', name=username, time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status='sleep')
    if record == True:
        text1 = f'{botname}已经记录下{username}的睡觉时间啦~'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text1)
    else:
        text1 = f'{botname}没能记录下{username}的睡眠时间呢，找 @acherkrau 问问是怎么回事吧!'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text1)


async def niubi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if helper.random_unit(pr_niubi):
        text = getWords.get_niubi().format(botname=botname)
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


async def weni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = getWords.get_weni(update.effective_message.text)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    name = update.effective_chat.username
    msg = update.effective_message.text
    text2master = f'刚刚{name}对我说：{msg}'
    await context.bot.send_message(chat_id=master_id, text=text2master)


async def at_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = getWords.get_at_reply().format(botname=botname)
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
    weni_handler = MessageHandler(filter_weni, weni)
    at_reply_handler = MessageHandler(filter_at, at_reply)

    handlers = [start_handler, unknown_handler, setu_handler, ohayo_handler,
                wanan_handler, niubi_handler, fileid_handler, yinyu_handler, weni_handler, at_reply_handler]
    application.add_handlers(handlers)

    application.run_polling()


if __name__ == '__main__':
    run()
