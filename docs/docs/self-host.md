# 部署指南

启动 Bot 之前, 需要为 Bot **设置头像**, 并关闭隐私模式

## 使用 docker-compose
### 最简配置

一般情况下仅需要 Bot Token 和你的 ID 即可启动一个 kmua 实例.

下载 [docker-compose.yml](https://github.com/krau/kmua-bot/blob/v2/docker-compose.yml)

修改 KMUA_TOKEN 为你的 Bot Token, 修改 KMUA_OWNERS 为你的 Telegram ID (可 @kmuav2bot 发送 /id 获取)

```bash
docker compose up -d
```

### 高级设置

如果你有更多需求, 请使用以下 `docker-compose.yml`.

```yaml
services:
  kmua:
    image: ghcr.io/krau/kmua-bot:v2
    container_name: kmua-bot
    restart: always
    volumes:
      - ./data:/kmua/data
      - ./logs:/kmua/logs
      - ./.secrets:/kmua/.secrets
    env_file:
      - .env
    network_mode: host
```

在同目录下新建 `.env` 文件, 参照下方的环境变量说明进行配置.

#### 常规

- `KMUA_TOKEN` - Bot Token
- `KMUA_OWNERS` - (数组) Bot 主人的 Telegram ID 
- `KMUA_LOG_LEVEL` - 日志级别, 默认 `INFO`, 可选 `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`
- `KMUA_LOG_RETENTION_DAYS` - 日志保留天数
- `KMUA_DB_URL` - 数据库连接地址, 默认 `sqlite:///./data/kmua.db`
- `KMUA_MAX_DB_SIZE` - sqlite 数据库文件最大大小, 到达后自动清理头像缓存, 默认 100MB
- `TZ` - 时区, 默认 `Asia/Shanghai`.

#### Bot API

- `KMUA_BASE_URL` - Bot API 地址, 默认 `https://api.telegram.org/bot` (官方)
- `KMUA_BASE_FILE_URL` - Bot 文件 API 地址, 默认 `https://api.telegram.org/file/bot`

#### Webhook

- `KMUA_WEBHOOK` - 是否启用 Webhook, 默认 `false`
- `KMUA_LISTEN` - Webhook 监听地址
- `KMUA_PORT` - Webhook 监听端口
- `KMUA_WEBHOOK_URL` - Webhook URL
- `KMUA_SECRET_TOKEN` - Webhook 验证 Token

#### 扩展功能
##### ManyACG (随机涩图)

- `KMUA_MANYACG_API` - ManyACG API 地址
- `KMUA_MANYACG_TOKEN` - ManyACG api token

##### Bilibili link (b 站链接转换)

- `KMUA_BILILINK_CONVERT_API` - Bilibili 链接转换 API 地址

##### Vertex AI (智能回复)

该功能需要 Redis, 请自行部署.

- `KMUA_VERTEX_SYSTEM` - Vertex AI 系统提示词
- `KMUA_VERTEX_PROJECT_ID` - Vertex AI 项目 ID
- `KMUA_VERTEX_LOCATION` - Vertex AI 位置
- `KMUA_VERTEX_MODEL` - Vertex AI 模型
- `KMUA_REDIS_URL` - Redis 连接地址
- `KMUA_VERTEX_PRESET` - (数组) 预设对话. 先用户后模型交替, 请确保数组长度为偶数且不超过16.
- `GOOGLE_APPLICATION_CREDENTIALS` - Google Application Credentials 路径. 请将 JSON 文件挂载到容器内.

### 完整 .env 示例

```dotenv
KMUA_TOKEN = "token"
KMUA_OWNERS = [114514]
KMUA_LOG_LEVEL = "INFO"
KMUA_DB_URL = "sqlite:///./data/kmua.db"
KMUA_BILILINK_CONVERT_API = "http://1.2.3.4:39080"
KMUA_LOG_RETENTION_DAYS = 8
KMUA_MANYACG_API = "http://1.0.1.0:39120"
KMUA_MANYACG_TOKEN = "token"
KMUA_LOG_RETENTION_DAYS=7
KMUA_WEBHOOK = false
KMUA_LISTEN = "127.0.0.1"
KMUA_PORT = 39391
KMUA_SECRET_TOKEN = "qwqowo"
KMUA_WEBHOOK_URL = "https://kmua.kmua.com"
TZ = Asia/Shanghai
KMUA_MAX_DB_SIZE=200
KMUA_BASE_URL = "https://api.telegram.org/bot"
KMUA_BASE_FILE_URL = "https://api.telegram.org/file/bot"
KMUA_VERTEX_SYSTEM= "你是一只名字叫kmua的可爱的猫娘."
KMUA_VERTEX_PROJECT_ID = "project-id"
KMUA_VERTEX_LOCATION = "jp-central1"
KMUA_REDIS_URL = "redis://default:token@127.0.0.1:6379/"
KMUA_VERTEX_MODEL = "gemini-1.0-pro"
GOOGLE_APPLICATION_CREDENTIALS=/kmua/.secrets/.secret.json
KMUA_VERTEX_PRESET = ["你好","喵~ 您好呀~ 今天天气真好呢~"]
```

## 源码运行

Python 版本: 3.12+, 在系统中需安装 `graphviz` 用于绘制关系图.

1. git clone https://github.com/krau/kmua-bot.git
2. 修改 `settings.toml` (参考上述环境变量设置, 但不需要 `KMUA_` 前缀, 且不必大写)
3. 使用你喜欢的工具创建虚拟环境 (建议 Poetry or venv), 安装依赖
4. `python -m kmua`