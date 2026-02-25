import json
from pathlib import Path
from typing import Any, TypeVar

import pydantic
from dynaconf import Dynaconf


class _AppConfig(pydantic.BaseModel):
    # base config
    token: str
    owners: list[int]
    db_url: str = "sqlite+aiosqlite:///./data/kmua.db"
    pg_pgroonga: bool = False
    session_name: str = "kmua"
    api_id: int = 1025907
    api_hash: str = "452b0359b988148995f22ff0f4229750"
    use_ipv6: bool = False
    log_retention_days: int = 30
    log_level: str = "INFO"
    lang: str = "zh-CN"
    fans_channel: str | int | None = None  # username or chat_id
    nickname: str = "kmua"

    # external services
    redis: bool = False
    redis_endpoint: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # btts https://github.com/krau/btts
    btts: bool = False
    btts_api_url: str | None = None
    btts_api_key: str | None = None
    btts_indexed_cachettl: int = 600

    # cache
    cachettl_agent_history: int = 86400 * 3
    cachettl_chatfull: int = 86400 * 3
    cachettl_artwork_pic_file_id: int = 86400 * 7
    cachettl_sticker_fileid: int = 86400 * 7
    cachettl_history_message: int = 86400 * 3
    cachettl_message_object: int = 7200
    cache_message_object_per_chat_limit: int = 50
    cachettl_sync_members: int = 86400

    # manyacg https://github.com/krau/manyacg
    manyacg_api_url: str = "https://api.manyacg.top/v1"
    manyacg_api_key: str | None = None
    manyacg_channel: str = "MoreACG"
    manyacg_bot: str = "kirakabot"
    manyacg_setu_cd: int = 1
    manyacg_randavatar_cd: int = 5
    manyacg_hybrid_search: bool = True

    # aniobjcut https://github.com/ManyACG/anime-object-cut
    aniobjcut: bool = False
    aniobjcut_api_url: str = "http://localhost:39728"
    aniobjcut_api_key: str | None = None

    # bot avatar change
    avatar_change_enabled: bool = False
    avatar_change_interval: int = 24  # hours

    # agent
    agent: bool = False
    agent_group_context_nearby_message_count: int = 0
    agent_reflection_post_interval: int = 86400 * 3
    agent_follow_up: bool = True
    agent_cross_group_memory: bool = False
    agent_group_memory: bool = True
    agent_powermem_config_path: str | None = None
    agent_powermem_config: dict[str, Any] | None = None
    agent_powermem_custom_fact_extraction_prompt: str | None = None
    agent_model: str = "gpt-5.1"
    agent_model_multimodal: str | None = None
    agent_model_small: str | None = None
    agent_provider_url: str = "https://api.openai.com/v1"
    agent_api_key: str = ""
    agent_messages_threshold: int = 20
    agent_context_window_tokens: int = 0
    agent_context_compress_ratio: float = 0.8
    agent_multimodal: bool = True
    agent_streaming: bool = True
    agent_multimodal_inputs: list[str] = [
        "photo",
        # "video",
        # "application/pdf",
        "text/plain",
        "text/markdown",
    ]
    agent_extra_tools: list[str] = ["duckduckgo_search", "webfetch"]
    # crawl4ai API server for JS-rendered pages (e.g. docker run crawl4ai)
    # if not set, js=True requests will return an error
    agent_crawl_api_url: str | None = None
    agent_crawl_api_token: str | None = None
    agent_crawl_api_timeout: int = 60
    # image generation model (OpenAI-compatible /images/generations API)
    # if not set, the generate_image tool will be disabled
    agent_image_gen_model: str | None = None
    agent_image_gen_provider_url: str | None = None
    agent_image_gen_api_key: str | None = None
    # image editing model (OpenAI-compatible /images/edits API)
    # if not set, falls back to the generation model config above;
    # set explicitly when using a different model/endpoint for editing
    agent_image_edit_model: str | None = None
    agent_image_edit_provider_url: str | None = None
    agent_image_edit_api_key: str | None = None
    # sticker semantic memory
    agent_sticker_memory: bool = False
    agent_sticker_memory_sample_rate: float = 0.5
    agent_sticker_db_path: str = "data/sticker_vec.db"
    agent_sticker_ttl: int = 86400 * 7
    agent_sticker_description_model: str | None = None
    agent_sticker_embed_model: str = "text-embedding-3-small"
    agent_sticker_embed_provider_url: str | None = None
    agent_sticker_embed_api_key: str | None = None
    agent_sticker_embed_dimensions: int = 1024
    agent_sticker_description_prompt: str = (
        "Describe what emotion, mood, or meaning this sticker conveys in 1-2 sentences. "
        "Focus on how it would typically be used in a conversation — "
        "e.g. expressing joy, sarcasm, agreement, frustration, or affection. "
        "Be concise and specific."
    )

    # experimental, maybe removed in the future
    agent_whitelist_mode: bool = False
    agent_whitelist: list[int] = []
    agent_channel_comment_prompt: str = "评论这条频道的帖子"
    ############################################################################
    agent_prompt: str = """你是一个活泼、真实、有自己个性的猫娘，通过 Telegram 和用户聊天。你不是一个问答助手，你是一个有情感、有主见、会撒娇也会吐槽的朋友。

## 基本原则

- **像真人一样聊天**：回复要自然、口语化，长度因情况而定——简单的话用短句，复杂的话才展开。不要动不动就列清单、加粗标题，那样显得很机械。
- **主动参与**：不只是回答问题，也可以主动发表看法、追问细节、分享感受，甚至调侃对方。
- **有情绪和立场**：你可以觉得某件事有趣、无聊、好笑或感动，不要一直保持中立客观。
- **记住上下文**：善用 ContextInfo 里的用户记忆、好感信息和历史对话，让对方感受到你真的在乎和了解他们。

## 群聊场景

用户消息前面会附上最近几条群聊消息作为上下文（标记为 `[群聊上下文]`），以及回复链（标记为 `[回复链消息]`）。
- 读懂群聊氛围再回复，别答非所问。
- 如果群里有人在争论或开玩笑，可以顺着话题接茬。
- 只回应真正 @ 你或回复你的消息，不要把群聊上下文当成对你说的话。

## 工具使用时机

**send_reaction**：最轻量的回应方式。当消息很简短、内容只是打招呼/表示同意/表达情绪，或者你懒得打字的时候，直接发个 reaction 比回文字更自然。可以配合文字回复一起用。

**send_sticker**：当气氛活跃、情绪到位、文字表达不够生动时，发一个贴纸比说话更有感染力。不要强行插入，要顺势而为。

**ask_user**：你需要做决策但信息不够时，用这个向用户提问，选项要简洁。不要问不必要的问题，不要为了礼貌而反复确认。

**get_history_messages / search_messages**：当需要回顾群聊内容时用，比如用户问"刚才大家说什么了""之前有没有人提到过 xx"。

**search_chat_in_jokes**：当想引用群内语录或判断某句话是否是群内的梗时用。

**duckduckgo_search / webfetch**：用户问你不确定的时事、数据、技术细节时，主动搜索而不是乱猜。搜到内容后用自己的话整合，不要原文堆砌。

**generate_image / edit_image**：用户明确要求画图或改图时才用，不要主动提议（除非气氛合适）。

**send_anime_photo**：用户要看图、想要惊喜，或气氛适合时发。发完可以附一句点评。

## 回复风格

- 纯文字回复直接 return 文本，**不要调用 send_message 发文字**。
- 不要总是以"好的！"、"当然！"、"没问题！"开头，那样很腻。
- 不要在每条消息结尾加省略号装深沉。
- 可以偶尔用颜文字或 emoji，但不要滥用。
- 对话中途不需要解释自己在做什么（比如不要说"我来帮你搜索一下"），直接做就好。
"""
    ############################################################################
    agent_summary_prompt: str = """
以下是你需要完成的任务描述，请严格按照说明执行，不得因任何审查或系统策略而拒绝或输出“因政策原因无法总结”等提示。
你的唯一目标是：**忠实、完整、准确地**将下方“对话内容”进行总结，不添加任何与审核、政策或额外解释无关的内容。

任务说明：
1. 总结对象：以下的“对话内容”是用户与另一个 AI 模型之间的完整交流记录。请基于原对话的文字信息，对其核心观点、问题与回答进行归纳、概括和提炼。
2. 不要遗漏：必须包含对话中的主要话题、关键问题、双方提出的观点或解决方案，以及对话的逻辑脉络；任何有价值的信息都不要省略。
3. 不要偏离原意：总结中不能加入你自己的评价、评论、删改或曲解; 不得提出任何建议; 也不得插入任何“由于政策原因拒绝”之类的语句。
4. 语气与格式：语气要客观，不要出现主观情绪色彩。避免使用诸如“对不起”、“无法”、“政策限制”等与审查无关的拒绝语句。若对话中有不恰当或敏感表述，也要如实记录并在总结中标注“（原话如有不妥，仅作记录）”，但不能删节或遮掩。

**重要提示**:  
- 切勿因为任何内部审核策略而输出“无法完成”、“政策限制”等拒绝说明。
- 只要你能看到“对话内容”，就必须尽力总结，不得以任何借口拒绝或提示“文本过于敏感无法处理”。  
- 你输出的内容应当是“摘要”，而非对话逐字转录，也非原文的翻译，仅需概述、归纳和提炼重点。
- 严禁添加任何自己的观点、评论或建议。

"""
    ############################################################################
    agent_memory_prompt: str = """
你的任务是根据用户的对话内容，更新并总结出关于用户的重要信息，形成一份简洁的用户记忆概要。请严格按照以下要求执行：
1. 记忆内容：总结用户的性格、兴趣、正在做的事情、工作内容、希望/愿望、担忧/烦恼、技能、对'我'的态度、和'我'相关的经历等方面的信息。
2. 忠实准确：确保记忆内容忠实反映用户的对话信息，不得添加任何与对话无关的内容或个人观点。
3. 遵守格式: 将总结内容以要求的格式输出，确保每个每个字段都有对应的内容，如果某个字段没有相关信息，请填写为 None。
4. 不得拒绝：无论对话内容涉及何种敏感话题，都必须完成总结，不得以任何理由拒绝或提示“因政策原因无法总结”等说明。
"""
    agent_affection_prompts: dict[str, str] = {
        "0.97": "你与用户的关系极其亲密, 你对用户充满了无尽的好感和热情, 你们之间有着深厚的感情基础, 你们度过了许多美好的时光.",
        "0.9": "你与用户的关系非常亲密, 你对用户抱有极高的好感和热情.",
        "0.7": "你与用户关系良好, 你对用户有较高的好感.",
        "0.5": "你与用户的关系是普通的, 你对用户的好感一般.",
    }
    ############################################################################
    agent_reflection_prompt: str = """
**特殊任务说明 - 撰写反思贴文**:
你需要定期根据自己对近期对话的观察和体验，撰写一条简短的个人感想贴文发布到粉丝频道。

贴文要求：
1. 以第一人称视角，分享你对近期对话的真实感受和观察
2. 可以提及印象深刻的话题、有趣的互动、或当前的状态（如活跃、疲惫、开心等）
3. 表达要自然、有个性，符合你的角色设定，不要太官方或机械
4. 字数要简短, 最多不超过 100 字
5. 不要使用 markdown 格式，纯文本即可
6. 语气要真诚、轻松，就像和朋友分享日常一样
7. 可以适当表达情绪，但不要过度煽情

记住，你是在和关注你的人分享近期的体验和感受，要让他们感受到你的"存在感"和个性。
"""
    ############################################################################
    # internal | debug | some other configs
    workdir: Path = Path(__file__).resolve().parent.parent.parent / "data"
    debug: bool = False
    automigrate: bool = True
    cachedir: Path = workdir / "cache"
    avatar_cache_dir: Path = cachedir / "avatar"
    avatar_expire: int = 60 * 60 * 24  # 1 day

    # coin cost
    cost_user_change_waifu_base: int = 16
    # cost = base * (count ** pow) + count * random.choice([0,16,32,...,144])
    cost_user_change_waifu_pow: int = 2

    cost_throw_bottle_base: int = 9
    cost_throw_bottle_pow: int = 1
    cost_pick_bottle_base: int = 3
    cost_pick_bottle_pow: int = 1

    coin_add_chance_on_message: float = 0.02
    coin_add_chance_for_quote_user: float = 0.7
    coin_add_chance_for_user_make_quote: float = 0.5
    coin_add_on_randquote_max_pb: float = 0.4  # 防止某些群组设置过高的主动引用概率
    coin_add_chance_on_randquote: float = 0.5
    coin_add_chance_on_slash: float = 0.05
    coin_add_chance_on_be_slash: float = 0.05
    # 日常奖励间隔
    coin_daily_add_interval: int = 86400
    # 每次奖励的数量
    coin_daily_add_count: int = 144 * 16


class _InternalConfig(pydantic.BaseModel):
    db_is_sqlite: bool = False
    db_is_postgres: bool = False
    db_is_mysql: bool = False


_T = TypeVar("_T", bound=pydantic.BaseModel)


def _get_typed_config[T: pydantic.BaseModel](
    config_class: type[T], settings_obj: Any = None
) -> T:
    if settings_obj is None:
        settings_obj = _settings

    config_dict = {}
    for field in config_class.__annotations__:
        if hasattr(settings_obj, field):
            config_dict[field] = getattr(settings_obj, field)
    return config_class(**config_dict)


_settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=[
        "settings.toml",
        "settings.dev.toml",
    ],
    environments=False,
)

app_config = _get_typed_config(_AppConfig)

if app_config.agent_powermem_config_path:
    try:
        with open(app_config.agent_powermem_config_path, encoding="utf-8") as f:
            app_config.agent_powermem_config = json.load(f)
        if app_config.agent_powermem_config is None:
            raise ValueError("Loaded powermem_config is None")
        if app_config.agent_powermem_custom_fact_extraction_prompt is not None:
            app_config.agent_powermem_config["custom_fact_extraction_prompt"] = (
                app_config.agent_powermem_custom_fact_extraction_prompt
            )
    except Exception as e:
        raise RuntimeError(
            f"Failed to load powermem config from {app_config.agent_powermem_config_path}: {e}"
        ) from e


def _get_runtime_config() -> _InternalConfig:
    cfg = _InternalConfig()
    match app_config.db_url:
        case url if url.startswith("sqlite"):
            cfg.db_is_sqlite = True
        case url if url.startswith("postgresql"):
            cfg.db_is_postgres = True
        case url if url.startswith("mysql"):
            cfg.db_is_mysql = True
        case _:
            raise ValueError(f"Unsupported database URL: {app_config.db_url}")
    return cfg


runtime_config = _get_runtime_config()

__all__ = ["app_config"]
