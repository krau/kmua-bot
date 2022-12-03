import random,os,yaml
import telegram

class Helper:
    def __init__(self) -> None:
        pass

    def random_unit(self,p):
        '''随机执行
        :p 概率，在[0,1]区间内'''
        assert p >= 0 and p <= 1, "概率P的值应该处在[0,1]之间！"
        if p == 0:#概率为0，直接返回False
            return False
        if p == 1:#概率为1，直接返回True
            return True
        p_digits = len(str(p).split(".")[1])
        interval_begin = 1
        interval__end = pow(10, p_digits)
        R = random.randint(interval_begin, interval__end)
        if float(R)/interval__end < p:
            return True
        else:
            return False

    
    def read_config(self,config_name):
        '''读取配置'''
        config_path = os.path.join(os.path.abspath(os.path.dirname(os.path.dirname(__file__))),f'{config_name}')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = f.read()
        config = yaml.load(config, Loader=yaml.FullLoader)
        return config