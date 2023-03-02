from telegram.ext import filters
from telegram.ext.filters import MessageFilter
from .helper import Helper

helper = Helper()

config = helper.read_config('config.yml')
botname = config.get('botname', 'Kmua')

regex_setu = "涩图|色图|色色|涩涩"
regex_ohayo = "醒了|早起|下床|刚醒|睡醒|早安|早上好|睡过了|哦哈哟|ohayo|醒力"
regex_sleep = "睡觉|睡了|眠了|wanan|晚安|哦呀斯密|oyasimi|睡力"
regex_niubi = "bot|机器人|智械危机|Bot"
regex_yinyu = "[a-zA-Z]"
regex_noyinyu = f"[^krau|{botname}|{botname.lower()}|{botname.upper()}|@krauisme|@acherkrau]"
regex_at = f"{botname}|{botname.lower()}|{botname.upper()}"
regex_mcmod = r"www.mcmod.cn/class"
regex_into_dict = "入典|史官"
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

    def __init__(self, name: str = None, data_filter: bool = False, minlen: int = 2, maxlen: int = 16):
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
filter_ohayo = filters.Regex(regex_ohayo) & FilterTextLen()
filter_sleep = filters.Regex(regex_sleep) & FilterTextLen()
filter_niubi = filters.Regex(regex_niubi)
filter_yinyu = filters.Regex(regex_yinyu) & filters.Regex(
    regex_noyinyu) & FilterTextLen(minlen=2, maxlen=10)
filter_at = filters.Regex(regex_at)
filter_weni = FilterWeniKey() & (~filters.Regex(regex_at)) & FilterTextLen(
    minlen=1) & filters.ChatType.PRIVATE
filter_mcmod = filters.Regex(regex_mcmod)
filter_into_dict = (filters.Regex(regex_into_dict) &
                    FilterTextLen(minlen=1, maxlen=10))
