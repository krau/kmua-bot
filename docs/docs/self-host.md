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
      - ./data:/kmua/data
      - ./logs:/kmua/logs
    environment:
      - TZ=Asia/Shanghai
      - KMUA_TOKEN="你的token"
      - KMUA_OWNERS=[] # bot 的主人id, 是一个数组
      - KMUA_PICKLE_PATH="./data/data.pickle" # 数据文件保存路径, 如需更改, 则也要更改上面的挂载路径
      - KMUA_LOG_LEVEL="INFO" # 日志等级
```