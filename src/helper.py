import random
import os
import yaml
from datetime import datetime
import json
from .logger import Logger

logger=Logger(name='helper',show=True)

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
                    with open(sleep_data_path,'w') as f:
                        json.dump({},f,ensure_ascii=False)
                data = {name: {"time": time, "status": status}}
                with open(sleep_data_path, 'r') as f:
                    content = json.load(f)
                content.update(data)
                with open(sleep_data_path, 'w') as f:
                    json.dump(content, f,indent=4,ensure_ascii=False)
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
