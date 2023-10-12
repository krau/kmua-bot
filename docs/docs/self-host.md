# 部署指南

## 使用 docker-compose

新建文件夹, 新建文件 `docker-compose.yml`

加入并修改以下内容

```yml
version: "3"
services:
  kmua:
    image: ghcr.io/krau/kmua-bot:v2
    container_name: kmua-main
    restart: always
    volumes:
      - ./data:/kmua/data
      - ./logs:/kmua/logs
    environment:
      - TZ=Asia/Shanghai
      - KMUA_TOKEN="你的token"
      - KMUA_OWNERS=[] # 主人id, 是一个数组
      - KMUA_LOG_LEVEL="INFO"
      - KMUA_DB_URL="sqlite:///./data/kmua.db"
      - KMUA_BILILINK_CONVERT_API="" # 可选，用于转换b站链接, 见 https://github.com/krau/bililink-converter
```

## 源码运行

Python版本: 3.11+

1. `git clone https://github.com/krau/kmua-bot`
2. pip install -r requirements.txt
3. edit settings.toml
4. python -m kmua