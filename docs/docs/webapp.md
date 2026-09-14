# 管理面板

kmua 内置一个基于 [Telegram Mini Apps](https://core.telegram.org/bots/webapps) 的管理面板, 在 Telegram 里直接配置 bot.

## 前置条件

1. 域名及其证书
2. 在 [@BotFather](https://t.me/BotFather) 为 bot 注册一个 Mini App

使用 docker 部署时, 前端产物已经打包进镜像

## 注册 Mini App

在 [@BotFather](https://t.me/BotFather) 里发 `/newapp`, 选择你的 bot, 然后按提示填写:

| 字段 | 填什么 |
| --- | --- |
| Title | 随便, 例如 `kmua 管理面板` |
| Description | 随便 |
| Photo | 640x360 图片, 必填 |
| Web App URL | `https://panel.example.com` |
| Short name | `panel` |

Web App URL 要和配置里的 `webapp_url` 完全一致, Short name 要和 `webapp_short_name` 一致.

## 修改配置

在 `settings.toml` 里添加如下配置:

```toml
webapp = true
webapp_url = "https://panel.example.com"
webapp_short_name = "panel"
```

## 启动

```bash
docker compose pull
docker compose up -d
docker compose logs -f kmua
```

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