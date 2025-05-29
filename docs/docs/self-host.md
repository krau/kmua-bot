# 部署指南

启动 Bot 之前, 需要为 Bot **设置头像**, 并关闭隐私模式

## 使用 docker-compose

一般情况下仅需要 Bot Token 和你的 ID 即可启动一个 kmua 实例.

下载 [docker-compose.yml](https://github.com/krau/kmua-bot/blob/v2/docker-compose.yml)

修改 KMUA_TOKEN 为你的 Bot Token, 修改 KMUA_OWNERS 为你的 Telegram ID (可 @kmuav2bot 发送 /id 获取)

```bash
docker compose up -d
```

## 源码运行

Python 版本: 3.13+, 在系统中需安装 `graphviz` 用于绘制关系图.

1. git clone https://github.com/krau/kmua-bot.git
2. 修改 `settings.toml`
3. 使用你喜欢的工具创建虚拟环境 (建议 uv), 安装依赖
4. `python -m kmua`