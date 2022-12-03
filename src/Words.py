import httpx
import json
import os
import random
from src.Helper import Helper

helper = Helper()

config = helper.read_config('config.yml')
name = config.get('botname', 'Kmua')

words_path = os.path.join('../', os.getcwd(), 'data/words')

aoligei_path = os.path.join(words_path, 'aoligei.json')
niubi_path = os.path.join(words_path, 'niubi.json')
#sese_path = os.path.join(words_path, 'sese.json')
wanan_path = os.path.join(words_path, 'wanan.json')
young_path = os.path.join(words_path, 'young.json')
ohayo_path = os.path.join(words_path, 'ohayo.json')

with open(aoligei_path, 'r') as f:
    aoligei_words = json.load(f)

with open(niubi_path, 'r') as f:
    niubi_words = json.loads(f.read().replace('botname', name))

with open(wanan_path, 'r') as f:
    wanan_words = json.load(f)

with open(young_path, 'r') as f:
    young_words = json.load(f)

with open(ohayo_path, 'r') as f:
    ohayo_words = json.load(f)


class GetWords():
    def __init__(self):
        self.aoligei = aoligei_words
        self.niubi = niubi_words
        self.wanan = wanan_words
        self.young = young_words
        self.ohayo = ohayo_words

    def get_aoligei(self):
        '''获取正能量'''
        return random.choice(self.aoligei)

    def get_niubi(self):
        '''获取装b句子'''
        return random.choice(self.niubi)

    def get_wanan(self):
        '''晚安!'''
        return random.choice(self.wanan)

    def get_young(self):
        '''获取大老师语录'''
        return random.choice(self.young)

    def get_ohayo(self):
        '''早安!'''
        return random.choice(self.ohayo)
