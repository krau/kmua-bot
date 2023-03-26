import logging
from logging import handlers

logger = logging.getLogger(name='ARIA2BOT')
日志格式 = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s: - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
流处理器 = logging.StreamHandler()
流处理器.setLevel(logging.INFO)
流处理器.setFormatter(日志格式)
logger.addHandler(流处理器)

时旋文件处理器 = handlers.TimedRotatingFileHandler(
    filename='./log/kmuabot.log',
    when='D',
    interval=1,
    backupCount=7,
    encoding='utf-8'
)

时旋文件处理器.setLevel(logging.DEBUG)
时旋文件处理器.setFormatter(日志格式)
logger.addHandler(时旋文件处理器)

logger.setLevel(logging.DEBUG)
