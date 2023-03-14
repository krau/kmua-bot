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
日志器 = Logger(name='bot', show=True)
日志器.info('bot启动中')
小工具 = Utils()
获取词 = GetWords()
mcmod = McMod()

'''读取设定配置'''
配置 = 小工具.read_config('config.yml')
日志器.info(f'读取配置...')
if 配置['代理地址']:
    os.environ['http_proxy'] = 配置['proxy']
    os.environ['https_proxy'] = 配置['proxy']
TOKEN = 配置['token']
botname = 配置['botname']
master_id = 配置['主人的id']
pr_nosese = 配置['概率_不要涩涩']
pr_sleep = 配置['概率_晚安']
pr_ohayo = 配置['概率_早安']
pr_niubi = 配置['概率_牛逼话']
pr_aoligei = 配置['概率_哲理']
pr_yinyu = 配置['概率_淫语']
pr_发典 = 配置.get('概率_发典', 0.01)
affair_notice = 配置.get('偷情监控', False)


'''初始化目录'''
if not os.path.exists('data'):
    os.mkdir('data')
if not os.path.exists('data/sleep_data.json'):
    with open('data/sleep_data.json', 'w') as f:
        json.dump({}, f, ensure_ascii=False)
if not os.path.exists('data/mods_data.json'):
    with open('data/mods_data.json', 'w') as f:
        json.dump({}, f, ensure_ascii=False)
if not os.path.exists('data/pics'):
    os.mkdir('data/pics')


async def 开始(update: Update, context: ContextTypes.DEFAULT_TYPE):
    日志器.info(f'收到来自{update.effective_chat.username}的/start指令')
    await context.bot.send_message(chat_id=update.effective_chat.id, text="喵呜?")
    await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM7Y4oxOY0Tkt5D5keXXph7jFE7U7YAAqUCAAJfIulXxC0Bkai8vqwrBA')


async def 开启偷情监控(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''开启偷情监控'''
    global affair_notice
    if update.effective_chat.id == master_id:
        affair_notice = True
        await context.bot.send_message(chat_id=master_id, text='已开启偷情监控')
        日志器.info(f'{update.effective_chat.username}开启了偷情监控')
    else:
        text = f"干嘛喵,{botname}不会这个~真的不会哦~"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 关闭偷情监控(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''关闭偷情监控'''
    global affair_notice
    if update.effective_chat.id == master_id:
        affair_notice = False
        await context.bot.send_message(chat_id=master_id, text='已关闭偷情监控')
        日志器.info(f'{update.effective_chat.username}关闭了偷情监控')
    else:
        text = f"干嘛喵,{botname}不会这个~真的不会哦~"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 设置群员权限(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        日志器.info(
            f'授予{update.effective_user.username} {custom_title}')
        text = f'好,你现在是{custom_title}啦'
        await context.bot.send_message(chat_id=chat_id, reply_to_message_id=update.effective_message.id, text=text)
    except Exception as e:
        text = f'不行! {e}'
        await context.bot.send_message(chat_id=chat_id, text=text)


async def 删除所有模组(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''删除所有模组数据'''
    try:
        if update.effective_user.id == master_id:
            os.remove('./data/mods_data.json')
            日志器.debug('删除:./data/mods_data.json')
            shutil.rmtree('./data/pics')
            日志器.debug('删除:./pics')
            await context.bot.send_message(chat_id=update.effective_chat.id, text='已经删除了所有保存的模组数据')
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAIFXGOhEyZbeuhLM41Y9BoyZUHAoGdjAAJRBAACV0C5VoqO8DRjKNWPLAQ')
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='不行!只有主人才可以!')
    except OSError as e:
        text = f'出错惹~{e}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 入典(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''入典'''
    try:
        msg_id = update.effective_message.reply_to_message.message_id
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg_id, disable_notification=False)
        日志器.info(f'入典:{update.effective_message.reply_to_message.text}')
        flag = 小工具.record_msg_id(
            chat_id=update.effective_chat.id, msg_id=msg_id)
        if flag == True:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='已入典')
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='置顶!')
    except Exception as e:
        text = f'不行! {e}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 取消入典(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''出典'''
    try:
        msg_id = update.effective_message.reply_to_message.message_id
        await context.bot.unpin_chat_message(chat_id=update.effective_chat.id, message_id=msg_id)
        flag = 小工具.delete_msg_id(
            chat_id=update.effective_chat.id, msg_id=msg_id)
        if flag == True:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='已出典')
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='不在典里,请回复被置顶的典,而不是被转发的典')
    except Exception as e:
        text = f'不行! {e}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 不要色色(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''不要涩涩'''
    if 小工具.random_with_probability(pr_nosese):
        await context.bot.send_message(chat_id=update.effective_chat.id, text='不要涩涩喵!')
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker='CAACAgUAAxkBAAM_Y4oxreCJwFtLa1okJMS3Xz7g8UsAAmYCAAImjuhXJN6lY6dZeNUrBA')


async def 早安(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''早安问候与睡眠时间计算'''
    if 小工具.random_with_probability(pr_ohayo):
        # text = 获取词.get_ohayo()
        stickers = ['CAACAgUAAxkBAAPnY4xM4SVJj5T5plvLUc89Lra77IUAAvACAAL30uhX8lw2t4mq6GErBA',
                    'CAACAgUAAxkBAANBY4oyECkXjRogFHgphC4lXWyL1XQAAuADAALYtOlXJmc1qHGknScrBA',
                    'CAACAgUAAxkBAAIDRGOZwXhR2FYfE21lyfE3ijFpPn7KAAI8AwACxNzoV7UXWq3xmh9pLAQ']
        # await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=random.choice(stickers))
    username = update.effective_user.full_name
    record = 小工具.sleep_recorder(mode='read', name=username)
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


async def 晚安(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''晚安与睡眠时间记录'''
    if 小工具.random_with_probability(pr_sleep):
        # text = 获取词.get_wanan()
        stickers = ['CAACAgUAAxkBAANEY4oyf4yTWS2IwdQI85PXUX4HQCUAAtkDAAJWFLhWB5Xyu3EaZwcrBA',
                    'CAACAgUAAxkBAANGY4oyj4NN8khNgBs7GYbuUExqUzoAAk4CAALWY0lV3OnyI0c9yfArBA',
                    'CAACAgUAAxkBAANKY4oyz3UNU7mIgitsGlNhb1CqH30AAm0DAAIytehXTdZ5bv72-fkrBA',
                    'CAACAgUAAxkBAANLY4oy08mWXoE0e3pIqR0Sz-Lm7yoAAqkDAAKUIOBXFZ5cO9IPe0crBA',
                    'CAACAgUAAxkBAAIDIWOYEVtJZs7H0SsQ2f_ggOMsSB_eAAK2CAAC5uiQVFV28zbFyciULAQ',
                    'CAACAgUAAxkBAAIDQmOZwVbDWOYeDFCQb9w49RgJHU40AAIyAgACN2XoV8kIAihs8kTlLAQ']
        sticker = random.choice(stickers)
        # await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=sticker)
    username = update.effective_user.full_name
    record = 小工具.sleep_recorder(
        mode='write', name=username, time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status='sleep')
    if record == True:
        text1 = f'{botname}已经记录下{username}的睡觉时间啦~'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text1)
    else:
        text1 = f'{botname}没能记录下{username}的睡眠时间呢，找 @acherkrau 问问是怎么回事吧!'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text1)


async def 牛逼(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''牛逼话'''
    if 小工具.random_with_probability(pr_niubi):
        text = 获取词.get_niubi().replace('botname', botname)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 淫语(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''yinyu翻译'''
    if 小工具.random_with_probability(pr_yinyu):
        message = update.effective_message.text
        en = 获取词.get_en(message)
        if len(en) > 1:
            yinyu = 获取词.get_yinyu(message)
            text = f'{en}: {yinyu}'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 获取file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''file_id获取给主人'''
    if update.effective_chat.id == master_id:
        file_id = update.message.sticker.file_id
        await context.bot.send_message(chat_id=update.effective_chat.id, text=file_id)
    else:
        if 小工具.random_with_probability(0.02):
            text = f'不要发表情包啦，{botname}还看不懂'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 文爱(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''文爱'''
    text = 获取词.get_weni(update.effective_message.text)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    if update.effective_chat.id != master_id and affair_notice == True:
        name = update.effective_chat.username
        msg = update.effective_message.text
        text2master = f'刚刚{name}对我说：{msg}'
        await context.bot.send_message(chat_id=master_id, text=text2master)


async def 当有人叫bot时回复(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''当有人叫bot时'''
    text = 获取词.get_at_reply().replace('botname', botname)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 发送模组数据(update: Update, context: ContextTypes.DEFAULT_TYPE, data_dict: dict):
    '''发送模组数据'''
    try:
        file = data_dict['file_name']
        mod_url = data_dict['mod_url']
        full_name = data_dict['full_name']
        async with aiofiles.open(f'./data/pics/{file}', 'rb') as f:
            photo = await f.read()
    except FileNotFoundError:
        text = f'无法找到截图文件：{file}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        return

    text = f'找到了这个模组~\n<b><a href="{mod_url}">{full_name}</a></b>'
    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=text, parse_mode='HTML')


async def 获取模组信息(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''自动获取mcmod上的模组信息'''
    mod_urls = 获取词.get_mcmod_url(text=update.effective_message.text)
    for mod_url in mod_urls:
        data_dict = mcmod.mod_data_read(mod_url=mod_url)
        if data_dict:
            await 发送模组数据(update=update, context=context, data_dict=data_dict)
            continue
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
        await 发送模组数据(update=update, context=context, data_dict=data_dict)


async def 输出已经保存的模组(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        text = f'失败了~{e}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 删除某个模组信息(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''删除某个模组信息'''
    try:
        mod_urls = 获取词.get_mcmod_url(
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
    except Exception as e:
        text = f'失败惹~{e}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def 随机转发入典的消息(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''随机转发入典的消息'''
    if 小工具.random_with_probability(pr_发典):
        msg_id = 小工具.read_msg_id(chat_id=update.effective_chat.id)
        if msg_id:
            await context.bot.forward_message(chat_id=update.effective_chat.id, from_chat_id=update.effective_chat.id, message_id=msg_id)
        else:
            pass


async def 设置发典概率(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''设置发典概率'''
    if update.effective_user.id != master_id:
        text = f'你没有权限设置发典概率哦~'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        return
    try:
        pr = float(update.effective_message.text.split(' ')[1])
        if pr > 1 or pr < 0:
            text = f'概率必须在0~1之间哦~'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            return
        global pr_发典
        pr_发典 = pr
        text = f'已经把发典概率设置为{pr}啦~'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    except Exception as e:
        text = f'失败啦! {e}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


def run():
    机器人 = ApplicationBuilder().token(TOKEN).build()

    开始处理器 = CommandHandler('start', 开始)
    开启偷情监控处理器 = CommandHandler(
        'enableaffairnotice', 开启偷情监控)
    关闭偷情监控处理器 = CommandHandler(
        'disableaffairnotice', 关闭偷情监控)
    设置群员权限处理器 = CommandHandler('p', 设置群员权限)
    删除所有模组处理器 = CommandHandler('rmallmods', 删除所有模组)
    入典命令处理器 = CommandHandler('q', 入典)
    删除某个模组信息处理器 = CommandHandler('rmmod', 删除某个模组信息)
    取消入典处理器 = CommandHandler('o', 取消入典)
    早安命令处理器 = CommandHandler('ohayo', 早安)
    晚安命令处理器 = CommandHandler('oyasumi', 晚安)
    设置发典概率处理器 = CommandHandler('setpr', 设置发典概率)

    不要色色处理器 = MessageHandler(filter_setu, 不要色色)
    早安消息处理器 = MessageHandler(filter_ohayo, 早安)
    晚安消息处理器 = MessageHandler(filter_sleep, 晚安)
    牛逼处理器 = MessageHandler(filter_niubi, 牛逼)
    获取file_id处理器 = MessageHandler(filters.Sticker.ALL, 获取file_id)
    淫语处理器 = MessageHandler(filter_yinyu, 淫语)
    文爱处理器 = MessageHandler(filter_weni, 文爱)
    当有人叫bot时回复处理器 = MessageHandler(filter_at, 当有人叫bot时回复)
    获取模组信息处理器 = MessageHandler(filter_mcmod, 获取模组信息)
    输出已经保存的模组处理器 = MessageHandler(
        filters.Regex('模组列表'), 输出已经保存的模组)
    入典消息处理器 = MessageHandler(filter_into_dict, 入典)
    随机转发入典的消息处理器 = MessageHandler(~filters.COMMAND, 随机转发入典的消息)

    处理器们 = [
        开始处理器,
        开启偷情监控处理器,
        关闭偷情监控处理器,
        设置群员权限处理器,
        删除所有模组处理器,
        删除某个模组信息处理器,
        入典命令处理器,
        入典消息处理器,
        取消入典处理器,
        早安命令处理器,
        晚安命令处理器,
        设置发典概率处理器,
        不要色色处理器,
        早安消息处理器,
        晚安消息处理器,
        牛逼处理器,
        获取file_id处理器,
        文爱处理器,
        当有人叫bot时回复处理器,
        获取模组信息处理器,
        输出已经保存的模组处理器,
        淫语处理器,
        随机转发入典的消息处理器
    ]
    机器人.add_handlers(处理器们)
    日志器.info('bot已开始运行')
    机器人.run_polling()


if __name__ == '__main__':
    run()
