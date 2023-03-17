from telegram.ext import filters
from telegram.ext.filters import MessageFilter
from .utils import Utils

utils = Utils()

config = utils.read_config('config.yml')
botname = config.get('botname', 'Kmua')

色图正则 = "涩图|色图|色色|涩涩"
早安正则 = "醒了|早起|下床|刚醒|睡醒了|早安|早上好|睡过了|哦哈哟|ohayo|醒力"
晚安正则 = "睡了|眠了|wanan|晚安|哦呀斯密|oyasimi|睡力"
牛逼话正则 = "bot|机器人|智械危机|Bot"
淫语正则 = "[a-zA-Z]"
不要淫语正则 = f"[^krau|{botname}|{botname.lower()}|{botname.upper()}|@krauisme|@acherkrau]"
艾特正则 = f"{botname}|{botname.lower()}|{botname.upper()}"
mcmod正则 = r"www.mcmod.cn/class"
入典正则 = "入典|史官"
文爱关键词 = utils.load_words('weni')


class FilterWeniKey(MessageFilter):
    '''文爱关键词过滤器'''

    def filter(self, message):
        try:
            weni_keys = 文爱关键词.keys()
            return any(key in message.text for key in weni_keys)
        except:
            return False


class FilterTextLen(MessageFilter):
    '''消息长度过滤器'''

    def __init__(self, name: str = None, data_filter: bool = False, minlen: int = 2, maxlen: int = 16):
        super().__init__(name, data_filter)
        self.minlen = minlen
        self.maxlen = maxlen

    def filter(self, message):
        if filters.Text(message) and self.minlen <= len(message.text) <= self.maxlen:
            return True
        else:
            return False


filter_setu = filters.Regex(色图正则)
filter_ohayo = filters.Regex(早安正则) & FilterTextLen()
filter_sleep = filters.Regex(晚安正则) & FilterTextLen()
filter_niubi = filters.Regex(牛逼话正则)
filter_yinyu = filters.Regex(淫语正则) & filters.Regex(
    不要淫语正则) & FilterTextLen(minlen=2, maxlen=10)
filter_at = filters.Regex(艾特正则)
filter_weni = FilterWeniKey() & (~filters.Regex(艾特正则)) & FilterTextLen(
    minlen=1) & filters.ChatType.PRIVATE
filter_mcmod = filters.Regex(mcmod正则)
filter_into_dict = (filters.Regex(入典正则) &
                    FilterTextLen(minlen=1, maxlen=10))
