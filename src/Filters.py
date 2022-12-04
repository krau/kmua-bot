from telegram.ext import filters
from telegram.ext.filters import MessageFilter
from .Helper import Helper
import telegram

helper = Helper()

config = helper.read_config('configtest.yml')
botname = config.get('botname', 'Kmua')

regex_setu = "涩图|色图|色色|涩涩"
regex_ohayo = "醒了|早起|下床|刚醒|睡醒|早安|早上好|睡过了|哦哈哟|ohayo"
regex_sleep = "睡觉|睡了|眠了|wanan|晚安|哦呀斯密|oyasimi"
regex_niubi = "bot|机器人|智械危机|Bot"
regex_yinyu = "[a-zA-Z]"
regex_noyinyu = f"[^krau|{botname}|{botname.lower()}|{botname.upper()}]"
regex_at = f"{botname}|{botname.lower()}|{botname.upper()}"


class FilterWeni(MessageFilter):
    def filter(self, message):
        if len(message.text) < 10:
            weni_keys = list(weni_words.keys())
            for weni_key in weni_keys:
                if message.text.find(weni_key) != -1:
                    return True
        else:
            return False


filter_setu = filters.Regex(regex_setu)
filter_ohayo = filters.Regex(regex_ohayo)
filter_sleep = filters.Regex(regex_sleep)
filter_niubi = filters.Regex(regex_niubi)
filter_yinyu = filters.Regex(regex_yinyu) & filters.Regex(regex_noyinyu)
filter_at = filters.Regex(regex_at)
filter_weni = FilterWeni() & (~filters.Regex(regex_at)) & filters.ChatType.PRIVATE

weni_words = helper.load_words('weni')
