from telegram.ext import filters
from telegram.ext.filters import MessageFilter
from .Helper import Helper

helper = Helper()

config = helper.read_config('config.yml')
botname = config.get('botname', 'Kmua')

regex_setu = "涩图|色图|色色|涩涩"
regex_ohayo = "醒了|早起|下床|刚醒|睡醒|早安|早上好|睡过了|哦哈哟|ohayo"
regex_sleep = "睡觉|睡了|眠了|wanan|晚安|哦呀斯密|oyasimi"
regex_niubi = "bot|机器人|智械危机|Bot"
regex_yinyu = "[a-zA-Z]"
regex_noyinyu = f"[^krau|{botname}|{botname.lower()}|{botname.upper()}|@krauisme|@acherkrau]"
regex_at = f"{botname}|{botname.lower()}|{botname.upper()}"
weni_words = helper.load_words('weni')

class FilterWeniKey(MessageFilter):
    '''文爱关键词过滤器'''
    def filter(self, message):
        try:
            weni_keys = list(weni_words.keys())
            for weni_key in weni_keys:
                if message.text.find(weni_key) != -1:
                    return True
            else:
                return False
        except:
            return False

class FilterTextLen(MessageFilter):
    '''消息长度过滤器'''
    def __init__(self, name: str = None, data_filter: bool = False, minlen:int = 2,maxlen:int = 16):
        super().__init__(name, data_filter)
        self.minlen = minlen
        self.maxlen = maxlen

    def filter(self, message):
        if filters.Text(message):
            if self.minlen <= len(message.text) <= self.maxlen:
                return True
            else:
                return False
        else:
            return False


filter_setu = filters.Regex(regex_setu)
filter_ohayo = filters.Regex(regex_ohayo)
filter_sleep = filters.Regex(regex_sleep)
filter_niubi = filters.Regex(regex_niubi)
filter_yinyu = filters.Regex(regex_yinyu) & filters.Regex(regex_noyinyu) & FilterTextLen()
filter_at = filters.Regex(regex_at)
filter_weni = FilterWeniKey() & (~filters.Regex(regex_at)) & FilterTextLen(minlen=1) & filters.ChatType.PRIVATE