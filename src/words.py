import random
import re
from .helper import Helper
from .bnhhsh.bnhhsh import dp
from .logger import Logger
logger = Logger(name='words',show=True)
helper = Helper()

config = helper.read_config('config.yml')
botname = config.get('botname', 'Kmua')

aoligei_words = helper.load_words('aoligei')
niubi_words = helper.load_words('niubi')
wanan_words = helper.load_words('wanan')
young_words = helper.load_words('wanan')
ohayo_words = helper.load_words('ohayo')
weni_words = helper.load_words('weni')
at_words = helper.load_words('at_reply')
weni_keys = list(weni_words.keys())


class GetWords():
    def __init__(self):
        self.aoligei = aoligei_words
        self.niubi = niubi_words
        self.wanan = wanan_words
        self.young = young_words
        self.ohayo = ohayo_words

    def get_aoligei(self) -> str:
        '''获取正能量'''
        return random.choice(self.aoligei)

    def get_niubi(self) -> str:
        '''获取装b句子'''
        return random.choice(self.niubi)

    def get_wanan(self) -> str:
        '''晚安!'''
        return random.choice(self.wanan)

    def get_young(self) -> str:
        '''获取大老师语录'''
        return random.choice(self.young)

    def get_ohayo(self) -> str:
        '''早安!'''
        return random.choice(self.ohayo)

    def get_yinyu(self, text) -> str:
        '''返回yinyu'''
        yinyu = dp(self.get_en(text).lower())
        return yinyu

    def get_en(self, text: str) -> str:
        '''返回句中的英文'''
        en = ''.join(re.findall(r'[a-zA-Z]', text))
        return en

    def get_weni(self, text: str) -> str:
        '''返回weni'''
        for weni_key in weni_keys:
            if text.find(weni_key) != -1:
                return random.choice(weni_words[weni_key])

    def get_at_reply(self) -> str:
        '''有人叫我'''
        return random.choice(at_words)

    def get_mcmod_url(self, text: str) -> list[str]:
        '''返回句中的mcmod页面链接列表'''
        pattern = re.compile(r"(https?:\/\/[^\s]+\/[0-9]+)(?:[^\u4e00-\u9fa5]*\.html)?")
        urls = re.findall(pattern, text)
        if urls:
            logger.debug(f'获取到mcmod链接{urls}')
            return urls
        else:
            logger.debug('无mcmod链接')
            return []