# 部署指南

## 使用 docker-compose

新建文件夹, 新建文件 `docker-compose.yml`

加入并修改以下内容

```yml
version: "3"
services:
  kmua:
    image: ghcr.io/krau/kmua-bot:v2
    container_name: kmua-v2-main
    init: true
    volumes:
      - ./data:/kmua/data # 数据路径, 目前不支持修改
      - ./logs:/kmua/logs
    environment:
      - TZ=Asia/Shanghai
      - KMUA_TOKEN="你的token"
      - KMUA_OWNERS=[] # bot 的主人id, 是一个数组
      - KMUA_PICKLE_PATH="./data/data.pickle" # pickle 数据保存路径, 目前不支持修改
      - KMUA_LOG_LEVEL="INFO" # 日志等级
      - KMUA_RANDOM_FILTER=0.1 # 随机过滤器概率,会影响某些随机功能的概率. 如 不能好好说话 在群聊中的随机发送
      - KMUA_PICKLE_UPDATE_INTERVAL=60 # pickle 文件的刷新间隔, 单位秒
```

## 源码运行

Python版本: 3.11+

1. `git clone https://github.com/krau/kmua-bot`
2. pip install -r requirements.txt
3. edit settings.toml
4. python bot.py