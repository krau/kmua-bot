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
        """
        该类用于提取消息特定文本，或是返回特定文本
        """
        logger.debug('实例化GetWords')
        self.aoligei = aoligei_words
        self.niubi = niubi_words
        self.wanan = wanan_words
        self.young = young_words
        self.ohayo = ohayo_words
        self.weni = weni_words
        self.at = at_words
        self.weni_keys = weni_keys

    def get_aoligei(self) -> str:
        '''获取正能量'''
        word =  random.choice(self.aoligei)
        logger.debug(f'获取到正能量:{word}')
        return word

    def get_niubi(self) -> str:
        '''获取装b句子'''
        word =  str(random.choice(self.niubi)).replace('botname',botname)
        logger.debug(f'获取到niubi:{word}')
        return word


    def get_wanan(self) -> str:
        '''晚安!'''
        word = random.choice(self.wanan)
        logger.debug(f'获取到晚安:{word}')
        return word

    def get_young(self) -> str:
        '''获取大老师语录'''
        word =  random.choice(self.young)
        logger.debug(f'获取到语录:{word}')
        return word

    def get_ohayo(self) -> str:
        '''早安!'''
        word =  random.choice(self.ohayo)
        logger.debug(f'获取到早安:{word}')
        return word

    def get_yinyu(self, text) -> str:
        '''返回yinyu'''
        yinyu = dp(self.get_en(text).lower())
        logger.debug(f'获取到yinyu:{yinyu}')
        return yinyu

    def get_en(self, text: str) -> str:
        '''返回句中的英文'''
        en = ''.join(re.findall(r'[a-zA-Z]', text))
        logger.debug(f'匹配到英文字符{en}')
        return en

    def get_weni(self, text: str) -> str:
        '''返回weni'''
        for weni_key in self.weni_keys:
            if text.find(weni_key) != -1:
                word = random.choice(self.weni[weni_key]).replace('botname',botname)
                logger.debug(f'获取到weni_word:{word}')
                return word

    def get_at_reply(self) -> str:
        '''有人叫我'''
        word =  str(random.choice(self.at)).replace('botname',botname)
        logger.debug(f'获取到at_reply:{word}')
        return word

    def get_mcmod_url(self, text: str) -> list[str]:
        '''返回句中的mcmod页面链接列表'''
        mod_nums = re.findall(r"www\.mcmod\.cn/class/([0-9]+)", text)
        urls = [f"https://www.mcmod.cn/class/{x}" for x in mod_nums]
        if urls:
            logger.debug(f'获取到mcmod链接{urls}')
            return urls
        else:
            logger.debug('无mcmod链接')
            return []