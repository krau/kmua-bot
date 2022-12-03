from telegram.ext import filters


regex_setu = "涩图|色图|色色|涩涩"
regex_ohayo = "醒了|早起|下床|刚醒|睡醒|早安|早上好|睡过了|哦哈哟|ohayo"
regex_sleep = "睡觉|睡了|眠了|wanan|晚安|哦呀斯密|oyasimi"
regex_niubi = "kmua"

filter_setu = filters.Regex(regex_setu)
filter_ohayo = filters.Regex(regex_ohayo)
filter_sleep = filters.Regex(regex_sleep)
filter_niubi = filters.Regex(regex_niubi)