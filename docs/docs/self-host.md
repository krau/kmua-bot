# 部署指南

启动 Bot 之前, 请为 Bot 关闭隐私模式, 以接收群组消息. 此外还需要打开 Inline Mode 和 Inline Query Feedback.

上述配置都需要在 [BotFather](https://t.me/botfather) 中完成.

## 使用 docker compose

一般情况下仅需要 Bot Token 和你的 ID 即可启动一个 kmua 实例.

下载 [docker-compose.yml](https://github.com/krau/kmua-bot/blob/v2/docker-compose.yml) 和 [settings.toml](https://github.com/krau/kmua-bot/blob/v2/settings.toml) 到同一目录下, 然后按需修改配置.


```bash
docker compose up -d
```

## 源码运行

Python 版本: 3.13+, 在系统中需安装 `graphviz` 用于绘制关系图.

1. git clone https://github.com/krau/kmua-bot.git
2. 修改 `settings.toml`
3. 使用 uv 创建虚拟环境, 安装依赖
4. `python -m kmua`