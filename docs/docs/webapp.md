# 管理面板

kmua 内置一个基于 [Telegram Mini Apps](https://core.telegram.org/bots/webapps) 的管理面板, 在 Telegram 里直接配置 bot.

## 前置条件

Telegram 只会打开 **HTTPS** 的 Mini App, 所以你需要:

1. 一个域名, 以及一个在前面终止 TLS 的反向代理
2. 在 [@BotFather](https://t.me/BotFather) 为 bot 注册一个 Mini App

前端产物已经打进镜像, 服务器上不需要装 Node 或跑构建.

## 1. 注册 Mini App

在 [@BotFather](https://t.me/BotFather) 里发 `/newapp`, 选择你的 bot, 然后按提示填写:

| 字段 | 填什么 |
| --- | --- |
| Title | 随便, 例如 `kmua 管理面板` |
| Description | 随便 |
| Photo | 640x360 图片, 必填 |
| Web App URL | `https://panel.example.com` |
| Short name | `panel` |

Web App URL 要和配置里的 `webapp_url` 完全一致, Short name 要和 `webapp_short_name` 一致.

## 2. 配置反向代理

面板只监听 HTTP, TLS 由反代终止. API 和页面由同一个服务提供, 所以整个域名转发到同一个后端即可, 不要只转发 `/`.

`X-Forwarded-For` 需要透传, 否则限流会把所有请求算到反代身上, 一个人触发限流会影响所有用户.

## 3. 改配置

在 `settings.toml` 里加三行:

```toml
webapp = true
webapp_url = "https://panel.example.com"
webapp_short_name = "panel"
```

其余选项都有合理默认值.

## 4. 启动并验证

```bash
docker compose pull
docker compose up -d
docker compose logs -f kmua
```

日志里应该看到:

```
webapp: listening on http://0.0.0.0:8180 (panel + health)
```

`(panel + health)` 是关键. 如果显示 `(health only)`, 说明配置没通过检查, 上一行会有 error 说明原因.

## 入口

| 位置 | 怎么打开 |
| --- | --- |
| 私聊 | `/start` 里的"管理面板"按钮, 或聊天框旁的菜单按钮 |
| 群内 | `/panel` 直达本群配置页; `/config` 面板底部也有同样的按钮; `/start` 对本群 bot 管理员也会显示 |

群内的入口是一个链接而不是 Mini App 按钮: Telegram 只在私聊里给 `web_app` 按钮传递启动参数, 群里要用 `t.me/<bot>/<short_name>?startapp=` 的形式. 所以 `webapp_short_name` 必须和 BotFather 注册的一致, 否则群内入口不会出现.

群内 `/panel` 和 `/config` 都需要本群的 bot 管理权限.

## 完整配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `webapp` | `false` | 是否启用面板 |
| `webapp_host` | `"0.0.0.0"` | 监听地址 |
| `webapp_port` | `8180` | 监听端口 |
| `webapp_url` | `""` | 公网 HTTPS 基址, 启用面板时必填 |
| `webapp_short_name` | `"panel"` | BotFather 注册的 Mini App short name |
| `webapp_menu_button` | `true` | 是否把聊天菜单按钮指向面板 |
| `webapp_jwt_secret` | `""` | 会话令牌签名密钥, 留空则从 bot token 派生 |
| `webapp_jwt_ttl` | `21600` | 会话有效期(秒) |
| `webapp_initdata_ttl` | `300` | 启动参数有效期(秒) |
| `webapp_allow_origins` | `[]` | CORS 白名单, 仅本地开发用 |
| `webapp_trusted_proxies` | `["127.0.0.1", "::1"]` | 信任其 `X-Forwarded-For` 的地址 |
| `webapp_static_dir` | `""` | 前端产物目录, 留空用镜像内置的 |
| `webapp_admin_edit_user` | `true` | 是否允许后台编辑用户信息 |

## 关闭面板

面板出问题时不需要回滚镜像, 关掉即可:

```toml
webapp = false
```

```bash
docker compose restart kmua
```

bot 的全部聊天功能不受影响, 健康检查照常工作. 群配置仍可用 `/config` 的 inline 键盘操作.
