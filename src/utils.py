import random
import os
from datetime import datetime
import json
from .logger import logger
from telegram import Update
from telegram.ext import ContextTypes


def msg_logs_decorator(func):
    '''记录消息日志装饰器'''
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg_text = update.effective_message.text
        user = update.effective_user.name
        chat = update.effective_chat.title
        if not msg_text:
            msg_text = '(非文本消息)'
        logger.info(f'[{user}]({chat}): {msg_text})')
        return await func(update, context)
    return wrapper


class Utils:
    '''该类用于设置一些辅助的方法'''

    def __init__(self) -> None:
        logger.debug('实例化Utils')
        pass

    def random_with_probability(self, probability: float) -> bool:
        '''指定概率返回True或False'''
        assert 0 <= probability <= 1, "参数probability应该在[0,1]之间"
        if probability in (0, 1):
            return bool(probability)
        p_digits = len(str(probability).split(".")[1])
        interval_begin = 1
        interval_end = pow(10, p_digits)
        r = random.randint(interval_begin, interval_end)
        return float(r) / interval_end < probability

    def load_words(self, words: str):
        '''读取并加载词库'''
        words_path = os.path.join(
            os.getcwd(), 'data', 'words', f'{words}.json')
        try:
            with open(words_path, 'r', encoding='utf-8') as f:
                the_words_json = json.load(f)
            logger.debug(f'已载入词库：{words_path}')
            return the_words_json
        except Exception as e:
            logger.error(f'载入词库出错：{words_path}, {e}')
            return {'Exception': 'except'}

    def sleep_recorder(self, mode: str, name: str, time: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status: str = 'sleep'):
        '''睡眠记录器'''
        sleep_data_path = os.path.join(os.getcwd(), 'data', 'sleep_data.json')

        if mode == 'write':
            try:
                data = {name: {"time": time, "status": status}}
                with open(sleep_data_path, 'r+') as f:
                    try:
                        content = json.load(f)
                    except:
                        content = {}
                    content.update(data)
                    f.seek(0)
                    json.dump(content, f, indent=4, ensure_ascii=False)
                    f.truncate()
                logger.debug(f'写入睡眠数据{data}')
                return True
            except Exception as e:
                logger.debug(f'写入睡眠数据错误: {e}')
                return False

        elif mode == 'read':
            try:
                with open(sleep_data_path, 'r') as f:
                    content = json.load(f)
                data = content.get(name)
                logger.debug(f'读取到睡眠数据:{data}')
                return data
            except Exception as e:
                logger.debug(f'读取睡眠数据错误 {e}')
                return {}

        else:
            logger.debug('无效的模式')
            return False

    # 记录入典消息的msg_id，以json存储

    def record_msg_id(self, chat_id: int, msg_id: int):
        '''记录入典消息的msg_id，以json存储'''
        try:
            chat_id = str(chat_id)
            msg_id_path = os.path.join(os.getcwd(), 'data', 'msg_id.json')
            msg_ids = {}

            if os.path.exists(msg_id_path):
                with open(msg_id_path, 'r') as f:
                    msg_ids = json.load(f)

            if chat_id in msg_ids:
                msg_ids[chat_id].append(msg_id)
            else:
                msg_ids[chat_id] = [msg_id]

            with open(msg_id_path, 'w', encoding='utf-8') as f:
                json.dump(msg_ids, f, indent=2, ensure_ascii=False)

            logger.debug(f'已记录消息ID:{msg_id}')
            return True

        except Exception as e:
            logger.error(f'记录消息ID出错:{e}')
            return False

    # 读取入典消息的msg_id，随机返回一个

    def read_msg_id(self, chat_id: int):
        '''读取入典消息的msg_id'''
        try:
            chat_id = str(chat_id)
            msg_id_path = os.path.join(
                '../', os.getcwd(), 'data/msg_id.json')
            if not os.path.exists(msg_id_path):
                with open(msg_id_path, 'w') as f:
                    json.dump({}, f, ensure_ascii=False)
            with open(msg_id_path, 'r') as f:
                content = json.load(f)
            if len(content) == 0:
                return False
            elif not content.get(chat_id, None):
                return False
            else:
                msg_id = random.choice(content[chat_id])
                logger.debug(f'读取消息ID:{msg_id}')
                return msg_id
        except Exception as e:
            logger.error(f'读取消息ID出错:{e}')
            return False

    def delete_msg_id(self, chat_id: int, msg_id: int):
        '''删除入典消息的msg_id'''
        try:
            chat_id = str(chat_id)
            msg_id_path = os.path.join(os.getcwd(), 'data', 'msg_id.json')
            if not os.path.exists(msg_id_path):
                with open(msg_id_path, 'w') as f:
                    json.dump({}, f, ensure_ascii=False)
            with open(msg_id_path, 'r') as f:
                content = json.load(f)
            if len(content) == 0:
                return False
            elif not content.get(chat_id, None):
                return False
            else:
                content[chat_id].remove(msg_id)
                with open(msg_id_path, 'w') as f:
                    json.dump(content, f, ensure_ascii=False)
                logger.debug(f'已删除消息ID:{msg_id}')
                return True
        except Exception as e:
            logger.error(f'删除消息ID出错:{e}')
            return False
