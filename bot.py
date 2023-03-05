import os
import random
import aiofiles
from datetime import datetime
from telegram import Update
import shutil
import json
from telegram.ext import filters, MessageHandler, ApplicationBuilder, CommandHandler, ContextTypes
from src.utils import Utils
from src.filters import *
from src.words import GetWords
from src.logger import Logger
from src.mcmod import McMod


'''初始化类'''
logger = Logger(name='bot', show=True)
logger.info('bot启动中')
utils = Utils()
getWords = GetWords()
mcmod = McMod()

'''读取设定配置'''
config = utils.read_config('config.yml')
logger.info(f'读取配置...')
if config['代理地址']:
    os.environ['http_proxy'] = config['proxy']
    os.environ['https_proxy'] = config['proxy']
TOKEN = config['token']
botname = config['bot的名字']
master_id = config['主人的id']
pr_nosese = config['概率_不要涩涩']
pr_sleep = config['概率_晚安']
pr_ohayo = config['概率_早安']
pr_niubi = config['概率_牛逼话']
pr_aoligei = config['概率_哲理']
pr_yinyu = config['概率_淫语']
pr_发典 = config.get('概率_发典', 0.01)
affair_notice = config.get('偷情监控', False)


'''初始化目录'''
if not os.path.exists('data'):
    os.mkdir('data')
if not os.path.exists('data/sleep_data.json'):
    with open('data/sleep_data.json', 'w') as f:
        json.dump({}, f,ensure_ascii=False)
if not os.path.exists('data/mods_data.json'):
    with open('data/mods_data.json', 'w') as f:
        json.dump({}, f,ensure_ascii=False)
if not os.path.exists('data/pics'):
    os.mkdir('data/pics')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f'收到来自{update.effective_chat.username}的/start指令')
    await context.bot.send_message(chat_id=update.effective_chat.id, text="喵呜?")
    await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM7Y4oxOY0Tkt5D5keXXph7jFE7U7YAAqUCAAJfIulXxC0Bkai8vqwrBA')


async def enable_affair_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''开启偷情监控'''
    global affair_notice
    if update.effective_chat.id == master_id:
        affair_notice = True
        await context.bot.send_message(chat_id=master_id, text='已开启偷情监控')
        logger.info(f'{update.effective_chat.username}开启了偷情监控')
    else:
        text = f"干嘛喵,{botname}不会这个~真的不会哦~"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def disable_affair_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''关闭偷情监控'''
    global affair_notice
    if update.effective_chat.id == master_id:
        affair_notice = False
        await context.bot.send_message(chat_id=master_id, text='已关闭偷情监控')
        logger.info(f'{update.effective_chat.username}关闭了偷情监控')
    else:
        text = f"干嘛喵,{botname}不会这个~真的不会哦~"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def set_right(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''设置成员权限'''
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    bot_username_len = len(update._bot.name)
    custom_title = update.effective_message.text[3+bot_username_len:]
    if not custom_title:
        custom_title = update.effective_user.username
    try:
        await context.bot.promote_chat_member(chat_id=chat_id, user_id=user_id, can_manage_chat=True, can_manage_video_chats=True, can_pin_messages=True, can_invite_users=True)
        await context.bot.set_chat_administrator_custom_title(chat_id=chat_id, user_id=user_id, custom_title=custom_title)
        logger.info(
            f'授予{update.effective_user.username} {custom_title}')
        text = f'好,你现在是{custom_title}啦'
        await context.bot.send_message(chat_id=chat_id, reply_to_message_id=update.effective_message.id, text=text)
    except:
        await context.bot.send_message(chat_id=chat_id, text='不行!!')
        logger.info(f'授予{update.effective_user.username}管理员失败')


async def rm_all_mods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''删除所有模组数据'''
    try:
        if update.effective_user.id == master_id:
            os.remove('./data/mods_data.json')
            logger.debug('删除:./data/mods_data.json')
            shutil.rmtree('./data/pics')
            logger.debug('删除:./pics')
            await context.bot.send_message(chat_id=update.effective_chat.id, text='已经删除了所有保存的模组数据')
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAIFXGOhEyZbeuhLM41Y9BoyZUHAoGdjAAJRBAACV0C5VoqO8DRjKNWPLAQ')
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='不行!!不可以!')
    except OSError as e:
        logger.error(f'错误:rm_all_mods:{e.strerror}')
        await context.bot.send_message(chat_id=update.effective_chat.id, text='出错惹~')


async def into_dict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''入典'''
    try:
        msg_id = update.effective_message.reply_to_message.message_id
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg_id, disable_notification=False)
        logger.info(f'入典:{update.effective_message.reply_to_message.text}')
        flag = utils.record_msg_id(
            chat_id=update.effective_chat.id, msg_id=msg_id)
        if flag == True:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='已入典')
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='置顶!')
    except Exception as e:
        text = f'不行! {e}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        logger.error(f'错误:q:{e}')


async def nosese(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''不要涩涩'''
    if utils.random_with_probability(pr_nosese):
        await context.bot.send_message(chat_id=update.effective_chat.id, text='不要涩涩喵!')
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM_Y4oxreCJwFtLa1okJMS3Xz7g8UsAAmYCAAImjuhXJN6lY6dZeNUrBA')


async def ohayo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''早安问候与睡眠时间计算'''
    if utils.random_with_probability(pr_ohayo):
        text = getWords.get_ohayo()
        stickers = ['CAACAgUAAxkBAAPnY4xM4SVJj5T5plvLUc89Lra77IUAAvACAAL30uhX8lw2t4mq6GErBA',
                    'CAACAgUAAxkBAANBY4oyECkXjRogFHgphC4lXWyL1XQAAuADAALYtOlXJmc1qHGknScrBA',
                    'CAACAgUAAxkBAAIDRGOZwXhR2FYfE21lyfE3ijFpPn7KAAI8AwACxNzoV7UXWq3xmh9pLAQ']
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=random.choice(stickers))
    username = update.effective_user.full_name
    record = utils.sleep_recorder(mode='read', name=username)
    if record:
        sleep_time_str = record.get('time')
        sleep_time = datetime.strptime(sleep_time_str, '%Y-%m-%d %H:%M:%S')
        wake_time = datetime.strptime(datetime.now().strftime(
            '%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S')
        if wake_time > sleep_time:
            slumber_time = float(
                format(((wake_time-sleep_time).seconds / 3600), '.3f'))
            if 0.50 < slumber_time < 9.00:
                text = f'{username}上次睡觉是在{sleep_time_str},这次一共睡了{slumber_time}小时哦~'
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            elif 0.20 <= slumber_time <= 0.50:
                text = f'{username}这次只睡了{slumber_time}小时，要好好休息哦~'
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            elif 9.00 <= slumber_time <= 13.00:
                text = f'{username}这次睡了{slumber_time}小时!!下次需要{botname}叫醒你吗~'
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
                await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM_Y4oxreCJwFtLa1okJMS3Xz7g8UsAAmYCAAImjuhXJN6lY6dZeNUrBA')
            elif slumber_time > 13.00:
                text = f'{username}上次给{botname}说晚安是在{slumber_time}小时前呢~昨晚睡觉的时候肯定没说!!'
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            else:
                pass
        else:
            text = f'不对劲，算不出来{username}的睡眠时间呢，你可能上次睡觉的时候该不会给{botname}说的早安吧？'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    else:
        text = f'{username}上次睡觉没有和{botname}说晚安哦~虽然没有很不开心就是了!'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM_Y4oxreCJwFtLa1okJMS3Xz7g8UsAAmYCAAImjuhXJN6lY6dZeNUrBA')


async def wanan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''晚安与睡眠时间记录'''
    if utils.random_with_probability(pr_sleep):
        text = getWords.get_wanan()
        stickers = ['CAACAgUAAxkBAANEY4oyf4yTWS2IwdQI85PXUX4HQCUAAtkDAAJWFLhWB5Xyu3EaZwcrBA',
                    'CAACAgUAAxkBAANGY4oyj4NN8khNgBs7GYbuUExqUzoAAk4CAALWY0lV3OnyI0c9yfArBA',
                    'CAACAgUAAxkBAANKY4oyz3UNU7mIgitsGlNhb1CqH30AAm0DAAIytehXTdZ5bv72-fkrBA',
                    'CAACAgUAAxkBAANLY4oy08mWXoE0e3pIqR0Sz-Lm7yoAAqkDAAKUIOBXFZ5cO9IPe0crBA',
                    'CAACAgUAAxkBAAIDIWOYEVtJZs7H0SsQ2f_ggOMsSB_eAAK2CAAC5uiQVFV28zbFyciULAQ',
                    'CAACAgUAAxkBAAIDQmOZwVbDWOYeDFCQb9w49RgJHU40AAIyAgACN2XoV8kIAihs8kTlLAQ']
        sticker = random.choice(stickers)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=sticker)
    username = update.effective_user.full_name
    record = utils.sleep_recorder(
        mode='write', name=username, time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status='sleep')
    if record == True:
        text1 = f'{botname}已经记录下{username}的睡觉时间啦~'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text1)
    else:
        text1 = f'{botname}没能记录下{username}的睡眠时间呢，找 @acherkrau 问问是怎么回事吧!'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text1)


async def niubi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''牛逼话'''
    if utils.random_with_probability(pr_niubi):
        text = getWords.get_niubi().replace('botname', botname)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def yinyu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''yinyu翻译'''
    if utils.random_with_probability(pr_yinyu):
        message = update.effective_message.text
        en = getWords.get_en(message)
        if len(en) > 1:
            yinyu = getWords.get_yinyu(message)
            text = f'{en} 是 {yinyu} 的意思嘛?'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def re_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''file_id获取给主人'''
    if update.effective_chat.id == master_id:
        file_id = update.message.sticker.file_id
        await context.bot.send_message(chat_id=update.effective_chat.id, text=file_id)
    else:
        if utils.random_with_probability(0.03):
            text = f'不要发表情包啦，{botname}还看不懂'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def weni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''文爱'''
    text = getWords.get_weni(update.effective_message.text)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    if update.effective_chat.id != master_id and affair_notice == True:
        name = update.effective_chat.username
        msg = update.effective_message.text
        text2master = f'刚刚{name}对我说：{msg}'
        await context.bot.send_message(chat_id=master_id, text=text2master)


async def at_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''当有人叫bot时'''
    text = getWords.get_at_reply().replace('botname', botname)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def get_mcmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''自动获取mcmod上的模组信息'''
    mod_urls = getWords.get_mcmod_url(text=update.effective_message.text)
    for mod_url in mod_urls:
        try:
            data_dict = await mcmod.screenshot(mod_url=mod_url)
        except Exception as e:
            text = f'无法获取模组信息：{e}'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            continue

        if not data_dict:
            text = f'无法找到模组信息：{mod_url}'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            continue

        file = data_dict['file_name']
        full_name = data_dict['full_name']
        try:
            async with aiofiles.open(f'./data/pics/{file}', 'rb') as f:
                photo = await f.read()
        except FileNotFoundError as e:
            text = f'无法找到截图文件：{file}'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            continue

        text = f'找到了这个模组~\n<b><a href="{mod_url}">{full_name}</a></b>'
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=text, parse_mode='HTML')


async def saved_mods_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''输出已经保存的mods'''
    try:
        with open('./data/mods_data.json', 'r', encoding='UTF-8') as f:
            mods_data = json.load(f)
        if len(mods_data) == 0:
            text = f'{botname}还没有记下任何模组呢~'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            return
        text = f'{botname}已经记下了这些模组~\n'
        for mod in mods_data:
            mod_url = mods_data[mod]['mod_url']
            full_name = mods_data[mod]['full_name']
            mod_text = f'<b><a href="{mod_url}">{full_name}</a></b>\n'
            text += mod_text
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML')
    except Exception as e:
        logger.error(f'输出已经保存的mods失败: {e}')
        await context.bot.send_message(chat_id=update.effective_chat.id, text='失败惹,可能是消息太长了')


async def rm_mod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''删除某个模组信息'''
    try:
        mod_urls = getWords.get_mcmod_url(
            text=update.effective_message.text)
        with open('./data/mods_data.json', 'r', encoding='UTF-8') as f:
            mods_data = json.load(f)
        for mod_url in mod_urls:
            for mod in mods_data:
                if mod_url == mods_data[mod]['mod_url']:
                    del mods_data[mod]
                    text = f'已经删除了这个模组~\n<b><a href="{mod_url}">{mod}</a></b>'
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML')
                    with open('./data/mods_data.json', 'w', encoding='UTF-8') as f:
                        json.dump(mods_data, f,
                                  ensure_ascii=False, indent=4)
                    break
            else:
                text = f'没有找到这个模组呢:{mod_url}'
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    except:
        logger.error('异常:rm_mod')
        await context.bot.send_message(chat_id=update.effective_chat.id, text='失败惹')


async def outo_dict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''随机转发入典的消息'''
    if utils.random_with_probability(pr_发典):
        msg_id = utils.read_msg_id(chat_id=update.effective_chat.id)
        if msg_id:
            await context.bot.forward_message(chat_id=update.effective_chat.id, from_chat_id=update.effective_chat.id, message_id=msg_id)
        else:
            pass


def run():
    application = ApplicationBuilder().token(TOKEN).build()

    start_handler = CommandHandler('start', start)
    enable_affair_notice_handler = CommandHandler(
        'enableaffairnotice', enable_affair_notice)
    disable_affair_notice_handler = CommandHandler(
        'disableaffairnotice', disable_affair_notice)
    set_right_handler = CommandHandler('p', set_right)
    rm_all_mods_handler = CommandHandler('rmallmods', rm_all_mods)
    into_dict_cmd_handler = CommandHandler('q', into_dict)
    rm_mod_handler = CommandHandler('rmmod', rm_mod)

    setu_handler = MessageHandler(filter_setu, nosese)
    ohayo_handler = MessageHandler(filter_ohayo, ohayo)
    wanan_handler = MessageHandler(filter_sleep, wanan)
    niubi_handler = MessageHandler(filter_niubi, niubi)
    fileid_handler = MessageHandler(filters.Sticker.ALL, re_file_id)
    yinyu_handler = MessageHandler(filter_yinyu, yinyu)
    weni_handler = MessageHandler(filter_weni, weni)
    at_reply_handler = MessageHandler(filter_at, at_reply)
    get_mcmod_handler = MessageHandler(filter_mcmod, get_mcmod)
    saved_mods_list_handler = MessageHandler(
        filters.Regex('模组列表'), saved_mods_list)
    into_dict_msg_handler = MessageHandler(filter_into_dict, into_dict)
    outo_dict_handler = MessageHandler(~filters.COMMAND, outo_dict)

    handlers = [
        start_handler,
        enable_affair_notice_handler,
        disable_affair_notice_handler,
        set_right_handler,
        rm_all_mods_handler,
        rm_mod_handler,
        into_dict_cmd_handler,
        into_dict_msg_handler,
        setu_handler,
        ohayo_handler,
        wanan_handler,
        niubi_handler,
        fileid_handler,
        weni_handler,
        at_reply_handler,
        get_mcmod_handler,
        saved_mods_list_handler,
        yinyu_handler,
        outo_dict_handler
    ]
    application.add_handlers(handlers)
    logger.info('bot已开始运行')
    application.run_polling()


if __name__ == '__main__':
    run()
