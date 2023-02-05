import random
import os
import yaml
from datetime import datetime
import json
from .logger import Logger

logger = Logger(name='helper', show=True)


class Helper:
    '''该类用于设置一些辅助的方法'''

    def __init__(self) -> None:
        logger.debug('实例化Helper')
        pass

    def random_unit(self, p):
        '''随机执行
        :p 概率，在[0,1]区间内'''
        logger.debug('调用:Helper.random_unit')
        assert p >= 0 and p <= 1, "概率P的值应该处在[0,1]之间！"
        if p == 0:  # 概率为0，直接返回False
            return False
        if p == 1:  # 概率为1，直接返回True
            return True
        p_digits = len(str(p).split(".")[1])
        interval_begin = 1
        interval__end = pow(10, p_digits)
        R = random.randint(interval_begin, interval__end)
        if float(R)/interval__end < p:
            return True
        else:
            return False

    def read_config(self, config_name) -> dict:
        '''读取配置'''
        logger.debug('调用:Helper.read_config')
        config_path = os.path.join(os.path.abspath(
            os.path.dirname(os.path.dirname(__file__))), f'{config_name}')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = f.read()
        config = yaml.load(config, Loader=yaml.FullLoader)
        logger.debug(f'已载入配置{config_name}')
        return config

    def load_words(self, words: str):
        '''read and load 词库'''
        logger.debug('调用:Helper.load_words')
        words_path = os.path.join('../', os.getcwd(), 'data/words')
        the_word_path = os.path.join(words_path, words+'.json')
        try:
            with open(the_word_path, 'r') as f:
                the_words_json = json.load(f)
                logger.debug(f'已载入词库：{the_word_path}')
                return the_words_json
        except:
            logger.error(f'载入词库出错：{the_word_path}')
            return {'Exception': 'except'}

    def sleep_recorder(self, mode: str, name: str, time: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status: str = 'sleep'):
        '''睡眠记录器'''
        logger.debug('调用:Helper.sleep_recorder')
        sleep_data_path = os.path.join(
            '../', os.getcwd(), 'data/sleep_data.json')
        if mode == 'write':
            try:
                if not os.path.exists(sleep_data_path):
                    with open(sleep_data_path, 'w') as f:
                        json.dump({}, f, ensure_ascii=False)
                data = {name: {"time": time, "status": status}}
                with open(sleep_data_path, 'r') as f:
                    content = json.load(f)
                content.update(data)
                with open(sleep_data_path, 'w') as f:
                    json.dump(content, f, indent=4, ensure_ascii=False)
                logger.debug(f'写入睡眠数据{data}')
                return True
            except:
                return False
        elif mode == 'read':
            try:
                with open(sleep_data_path, 'r') as f:
                    content = json.load(f)
                data = content.get(name)
                logger.debug(f'读取到睡眠数据:{data}')
                return data
            except:
                logger.debug('读取睡眠数据错误')
                return {}
        else:
            return False

    # 记录入典消息的msg_id，以json存储
    def record_msg_id(self, chat_id: int, msg_id: int):
        '''记录入典消息的msg_id，以json存储'''
        logger.debug('调用:Helper.record_msg_id')
        try:
            chat_id = str(chat_id)
            msg_id_path = os.path.join(
                '../', os.getcwd(), 'data/msg_id.json')
            if not os.path.exists(msg_id_path):
                with open(msg_id_path, 'w') as f:
                    json.dump({}, f, ensure_ascii=False)
            with open(msg_id_path, 'r') as f:
                content = json.load(f)
            if content.get(chat_id, None):
                content[chat_id].append(msg_id)
            else:
                content[chat_id] = [msg_id]
            with open(msg_id_path, 'w') as f:
                json.dump(content, f, ensure_ascii=False)
            logger.debug(f'已记录消息ID:{msg_id}')
            return True
        except Exception as e:
            logger.error(f'记录消息ID出错:{e}')
            return False

    # 读取入典消息的msg_id，随机返回一个
    def read_msg_id(self, chat_id: int):
        '''读取入典消息的msg_id'''
        logger.debug('调用:Helper.read_msg_id')
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
                print('没有消息ID')
                return False
            elif not content.get(chat_id, None):
                print('没有chatID')
                return False
            else:
                msg_id = random.choice(content[chat_id])
                logger.debug(f'读取消息ID:{msg_id}')
                return msg_id
        except Exception as e:
            logger.error(f'读取消息ID出错:{e}')
            return False

    def black(self, id: int) -> bool:
        '''加入黑名单'''
        logger.debug('调用:Helper.black')
        try:
            black_path = os.path.join(
                '../', os.getcwd(), 'data/blacklist.json')
            if not os.path.exists(black_path):
                with open(black_path, 'w') as f:
                    json.dump([], f, ensure_ascii=False)
            with open(black_path, 'r') as f:
                content = json.load(f)
            if id not in content:
                content.append(id)
            with open(black_path, 'w') as f:
                json.dump(content, f, ensure_ascii=False)
            logger.debug(f'已加入黑名单:{id}')
            return True
        except Exception as e:
            logger.error(f'加入黑名单出错:{e}')
            return False

    def get_blacklist(self) -> list:
        '''获取黑名单'''
        logger.debug('调用:Helper.get_blacklist')
        try:
            black_path = os.path.join(
                '../', os.getcwd(), 'data/blacklist.json')
            if not os.path.exists(black_path):
                with open(black_path, 'w') as f:
                    json.dump([], f, ensure_ascii=False)
            with open(black_path, 'r') as f:
                content = json.load(f)
            logger.debug(f'黑名单:{content}')
            return content
        except Exception as e:
            logger.error(f'获取黑名单出错:{e}')
            return []

    def is_not_blacklist(self, id: int) -> bool:
        '''检查是否在黑名单'''
        logger.debug('调用:Helper.check_blacklist')
        try:
            black_path = os.path.join(
                '../', os.getcwd(), 'data/blacklist.json')
            if not os.path.exists(black_path):
                with open(black_path, 'w') as f:
                    json.dump([], f, ensure_ascii=False)
            with open(black_path, 'r') as f:
                content = json.load(f)
            if id in content:
                logger.debug(f'{id}在黑名单中')
                return False
            else:
                logger.debug(f'{id}不在黑名单中')
                return True
        except Exception as e:
            logger.error(f'检查黑名单出错:{e}')
            return True