<div align="center">
<img src="https://t.me/i/userpic/320/kmuav2bot.jpg" alt="kmua" width="240">

# kmua

*I can see you in most everything*

一个会聊天、会记事、会动手的 Telegram Agent, 顺带把群也管了.

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13-3776ab.svg)](https://www.python.org/)
[![Build and Publish Docker Image](https://github.com/krau/kmua-bot/actions/workflows/build-docker.yml/badge.svg?branch=v2)](https://github.com/krau/kmua-bot/actions/workflows/build-docker.yml)

[文档](https://kmua.unv.app) · [在线 Demo](https://t.me/kmuav2bot) · [自部署](https://kmua.unv.app/self-host/) · [命令列表](https://kmua.unv.app/help/)
</div>

## AI

**这才是本体.** 在 `settings.toml` 里把 `agent` 打开并配好模型接口 (兼容 OpenAI 的 Chat Completions / Responses, 也可自定义 provider), kmua 就从一个群管工具变成住在群里的 Agent:

- **对话** — 私聊直接说话; 群里回复她的消息、或者 @ 她一下就能触发. 支持多轮上下文、追问、以及用按钮向你反问
- **工具调用** — 联网搜索与读取网页、查 IP、拟时间、查库里的群与用户信息, 而不是靠幻觉
- **看图与画图** — 理解你发的图, 也能生成 / 编辑图片
- **表情包记忆** — 记住群里哪些贴纸适合什么场合, 在聊天里自己找时机发出来
- **记忆** — 群组长期记忆 + 每个用户的个人记忆, 会自己总结、也会在被送礼时忘掉不该记的东西
- **动手能力** — 在部署者开放后可以使用沙盒 shell、工作区文件; 还有一整个 `kmua-bot` 的代码仓库可读可搜, 所以她能看懂自己
- **Telegram 操作** — 自己加表情回应、发贴纸、拉黑人 (拉黑时长与好感度挂钩, 好感越高关小黑屋越短)
- **RSS 播报** — 订阅推送时自动生成摘要与播报
- **频道评论** — 对转发到群里的频道消息发表评论
- **配额计量** — 按 token 计费, 先扣个人免费额度, 再扣群额度, 提供 `/quota` 查看
- **可调教** — `/model` `/prompt` 换模型与系统提示词, 通过 providers 配置多模型与代理

AI 的态度会被**好感度**影响: 说话、记语录、"施法"会攒金币, 金币可以在私聊 `/buygift` 买礼物送给 bot, 有些礼物能提升好感度, 有些能清空她对你的记忆.

群管理可以在 `/config` 里单独关闭某个群的 AI 回复, 部署者也可以用白名单限定可用范围. 能力上限取决于配置, 细节见 [帮助文档](https://kmua.unv.app/help/).

## 简介

kmua 基于 [Kurigram](https://github.com/KurimuzonAkuma/kurigram) (Pyrogram fork) 开发, 用 [SQLAlchemy](https://www.sqlalchemy.org/) 存数据, 由 [FastAPI](https://fastapi.tiangolo.com/) 提供可选的 WebApp 管理面板, 以 AGPL 协议开源.

> 分支名中的 v2 仅代表设计理念上的第二代, 不作 major version 语义. 本项目随时可能会出现 breaking change, 更新前请查阅 commit history 并做好备份.

## 其他功能

- **语录** — `/q` 记录群友的精彩发言, `/qrand` 随机翻出来回味, 还能按概率主动插进群聊, 也支持 Inline 查询
- **每日老婆** — `/waifu` 抽取今日群友老婆, 可以求婚结婚, 也能生成关系图
- **漂流瓶** — 跨群的匿名漂流瓶, 可以扔回大海、追寻踪迹、给瓶主寄回信
- **群管理** — 欢迎语、群头衔、入群验证 (算术 / 表情 / 贴纸 / 自定义问答)、自动删除服务消息、群设置与 WebApp 面板
- **链接解析** — Pixiv / B 站 / Danbooru / Twitter 等插画链接自动解析, b23 短链还原, 微信公众号文章还原
- **随机涩图** — `/setu` 随机发图, 支持冷却与单群开关
- **RSS 订阅** — 订阅推送 (AI 可参与摘要与播报)
- **小工具** — 词云、信息图渲染、随机头像、`/id`、`/f5avatar`

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

可选依赖: [ManyACG](https://github.com/krau/ManyACG) (涩图与插画解析) 和 [infographic-api](https://github.com/krau/infographic-api) (信息图渲染), 未部署时相关命令会静默不响应.

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
