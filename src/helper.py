import random
import os
import yaml
from datetime import datetime
import json
from .logger import Logger

logger=Logger(name='helper',show=True)

class Helper:
    def __init__(self) -> None:
        pass

    def random_unit(self, p):
        '''随机执行
        :p 概率，在[0,1]区间内'''
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
        config_path = os.path.join(os.path.abspath(
            os.path.dirname(os.path.dirname(__file__))), f'{config_name}')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = f.read()
        config = yaml.load(config, Loader=yaml.FullLoader)
        logger.debug(f'已载入配置{config_name}')
        return config

    def load_words(self, words: str):
        '''read and load 词库'''
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
        sleep_data_path = os.path.join(
            '../', os.getcwd(), 'data/sleep_data.json')
        if mode == 'write':
            try:
                data = {name: {"time": time, "status": status}}
                with open(sleep_data_path, 'r') as f:
                    content = json.load(f)
                content.update(data)
                with open(sleep_data_path, 'w') as f:
                    json.dump(content, f)
                return True
            except:
                return False
        elif mode == 'read':
            try:
                with open(sleep_data_path, 'r') as f:
                    content = json.load(f)
                data = content.get(name)
                return data
            except:
                return {}
        else:
            return False
