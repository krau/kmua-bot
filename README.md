<div align="center">
<img src="https://t.me/i/userpic/320/kmuav2bot.jpg" alt="kmua" width="240">

# kmua

*I can see you in most everything*

一只什么都想掺一脚的 Telegram 机器人.

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13-3776ab.svg)](https://www.python.org/)
[![Build and Publish Docker Image](https://github.com/krau/kmua-bot/actions/workflows/build-docker.yml/badge.svg?branch=v2)](https://github.com/krau/kmua-bot/actions/workflows/build-docker.yml)

[文档](https://kmua.unv.app) · [在线 Demo](https://t.me/kmuav2bot) · [自部署](https://kmua.unv.app/self-host/) · [命令列表](https://kmua.unv.app/help/)
</div>

## 简介

kmua 基于 [Kurigram](https://github.com/KurimuzonAkuma/kurigram) (Pyrogram fork) 开发, 用 [SQLAlchemy](https://www.sqlalchemy.org/) 存数据, 由 [FastAPI](https://fastapi.tiangolo.com/) 提供可选的 WebApp 管理面板, 以 AGPL 协议开源.

她既是群管小工具, 也是能记住你说过什么、会被你惹生气、还能被你送礼哄好的话痨. 能力上限取决于部署者的配置, 命令列表见 [帮助文档](https://kmua.unv.app/help/).

> 分支名中的 v2 仅代表设计理念上的第二代, 不作 major version 语义. 本项目随时可能会出现 breaking change, 更新前请查阅 commit history 并做好备份.

## 功能

- **语录** — `/q` 记录群友的精彩发言, `/qrand` 随机翻出来回味, 还能按概率主动插进群聊
- **每日老婆** — `/waifu` 抽取今日群友老婆, 可以求婚结婚, 也能生成关系图
- **漂流瓶** — 跨群的匿名漂流瓶, 可以扔回大海、追寻踪迹、给瓶主寄回信
- **群管理** — 欢迎语、群头衔、入群验证、自动删除服务消息、群设置与 WebApp 面板
- **链接解析** — Pixiv / B 站 / Danbooru / Twitter 等插画链接自动解析, b23 短链还原, 微信公众号文章还原
- **随机涩图** — `/setu` 随机发图, 支持冷却与单群开关
- **RSS 订阅** — 订阅推送, 可由 AI 生成摘要播报
- **AI 对话** — 联网搜索与读网页、看图、发贴纸回应、记住群里的内容、评论频道转发
- **礼物与好感度** — 金币换礼物, 好感度会影响 AI 对你的态度
- **小工具** — 词云、信息图渲染、随机头像、IP 查询……

## 快速开始

只需要 Bot Token 和你的用户 ID 就能跑起来. 先在 [BotFather](https://t.me/botfather) 中关闭隐私模式 (Privacy Mode), 并打开 Inline Mode.

```bash
# 下载 docker-compose.yml 与 settings.toml 到同一目录, 按需修改配置
docker compose up -d
```

不使用 Docker 时也可以从源码运行, 需要 Python 3.13 与可用的 `graphviz`:

```bash
git clone https://github.com/krau/kmua-bot.git
uv sync
python -m kmua
```

数据库默认使用 SQLite (`sqlite+aiosqlite:///./data/kmua.db`), 也可以改成 PostgreSQL. 完整配置说明见 [自部署文档](https://kmua.unv.app/self-host/).

部分功能依赖额外的服务, 未部署时相关命令会静默不响应: [ManyACG](https://github.com/krau/ManyACG) (涩图与插画解析) 和 [infographic-api](https://github.com/krau/infographic-api) (信息图渲染).

## 文档

- [简介](https://kmua.unv.app/)
- [命令列表 / 详细帮助](https://kmua.unv.app/help/)
- [自部署](https://kmua.unv.app/self-host/)
- [WebApp 管理面板](https://kmua.unv.app/webapp/)

文档源码在 `docs/` 下, 欢迎 PR 补充.

## 贡献

欢迎 Issue 与 PR. 提交前请尽量:

- `uv run ruff check` 无新增告警, `uv run pytest` 通过
- 新增或修改命令时同步更新 `docs/docs/help.md`
- 遵循现有的代码风格与目录结构 (功能插件放在 `kmua/plugins/<功能>/`)

## 许可

本项目以 [AGPL-3.0](LICENSE) 协议开源.
