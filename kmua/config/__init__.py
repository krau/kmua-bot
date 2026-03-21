import json
from pathlib import Path
from typing import Any, TypeVar

import pydantic
from dynaconf import Dynaconf


class ProviderConfig(pydantic.BaseModel):
    """Named AI provider: base URL + API key pair."""

    url: str = "https://api.openai.com/v1"
    key: str = ""
    type: str = "chat_completions"
    """API compatibility type. Supported values:
    - "chat_completions": OpenAI Chat Completions API (default, broadly compatible)
    - "responses": OpenAI Responses API (newer OpenAI-native API)
    """


class _AppConfig(pydantic.BaseModel):
    # base config
    token: str
    owners: list[int]
    db_url: str = "sqlite+aiosqlite:///./data/kmua.db"
    # APScheduler job store database URL (sync)
    # If not set, uses db_url with async driver replaced by sync driver
    # Allows separating job storage from main database
    jobstore_db_url: str | None = None
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

    # health check server for container monitoring
    health_check_enabled: bool = False
    health_check_host: str = "localhost"
    health_check_port: int = 8180

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
    # Named providers: keys are provider names, values are {url, api_key}.
    # The "default" provider is used when a model spec has no explicit provider prefix.
    # Example:
    #   [agent_providers.openai]
    #   url = "https://api.openai.com/v1"
    #   api_key = "sk-..."
    #   [agent_providers.local]
    #   url = "http://localhost:11434/v1"
    #   api_key = "ollama"
    agent_providers: dict[str, ProviderConfig] = {"default": ProviderConfig()}
    # Model specs use the format "provider/model_name" or just "model_name"
    # (bare name uses the "default" provider).
    agent_model: str | None = "default/gpt-4.1"
    agent_model_multimodal: str | None = None  # falls back to agent_model if unset
    agent_model_small: str | None = None  # falls back to agent_model if unset
    agent_struct_model: str | None = None
    agent_messages_threshold: int = 20
    agent_context_window_tokens: int = 0
    agent_context_compress_ratio: float = 0.8
    # Layered compression: number of recent messages to keep fully intact
    agent_compression_recent_keep: int = 6
    # Whether to compress tool return content (truncates long outputs)
    agent_compression_compress_tool_returns: bool = True
    # Max length for compressed tool return content
    agent_compression_tool_return_max_length: int = 200
    agent_multimodal: bool = True
    agent_streaming: bool = True
    agent_multimodal_inputs: list[str] = [
        "photo",
        # "video",
        # "application/pdf",
    ]
    # Max multimodal items (images/video/binary) across user_prompt + history sent to model.
    # Oldest history items are stripped first when the total exceeds this limit.
    # 0 = no limit.
    agent_multimodal_max_items: int = 4
    agent_extra_tools: list[str] = ["duckduckgo_search", "webfetch"]
    # crawl4ai API server for JS-rendered pages (e.g. docker run crawl4ai)
    # if not set, js=True requests will return an error
    agent_crawl_api_url: str | None = None
    agent_crawl_api_token: str | None = None
    agent_crawl_api_timeout: int = 60
    # Agent model call timeouts (seconds) - 0 means no timeout
    agent_model_timeout: int = 0  # Main model timeout (0 = no timeout)
    agent_small_model_timeout: int = 10  # Small model timeout for quick tasks
    agent_download_timeout: int = 30  # Download media timeout (0 = no timeout)
    # Image generation/editing: "provider/model" spec.
    # Generation client is disabled when unset.
    agent_image_gen_model: str | None = None
    # Edit client falls back to gen model/provider when unset.
    agent_image_edit_model: str | None = None
    # Sticker semantic memory
    agent_sticker_memory: bool = False
    agent_sticker_memory_sample_rate: float = 0.5
    agent_sticker_db_path: str = "data/sticker_vec.db"
    agent_sticker_ttl: int = 86400 * 7
    agent_sticker_min_keep_count: int = 100  # 少于此数量时不逐出过期贴纸
    # Embedding model spec: "provider/model". Falls back to agent_model provider.
    agent_sticker_embed_model: str = "default/text-embedding-3-small"
    agent_sticker_embed_dimensions: int = 1024
    # Description model spec. Falls back to agent_model when unset.
    agent_sticker_description_model: str | None = None
    agent_sticker_description_prompt: str = (
        "Describe what emotion, mood, or meaning this sticker conveys in 1-2 sentences. "
        "Focus on how it would typically be used in a conversation — "
        "e.g. expressing joy, sarcasm, agreement, frustration, or affection. "
        "Be concise and specific."
    )
    # Periodic sticker / reaction: force-inject the tool hint every N conversations.
    # 0 = disabled.
    agent_periodic_sticker_interval: int = 7
    agent_periodic_reaction_interval: int = 7
    # Code self-awareness: allow agent to read its own codebase to understand other features
    agent_code_awareness: bool = True
    # Custom file patterns to exclude from code repository (in addition to default security exclusions)
    # Example: ["*.md", "docs/**/*", "tests/**/*"]
    agent_code_exclude_patterns: list[str] = []

    # experimental, maybe removed in the future
    agent_whitelist_mode: bool = False
    agent_whitelist: list[int] = []
    agent_channel_comment_prompt: str = "评论这条频道的帖子"
    ############################################################################
    agent_prompt: str = """"""
    agent_group_prompt: str = """"""
    ############################################################################
    agent_summary_prompt: str = """"""
    ############################################################################
    agent_memory_prompt: str = """"""
    agent_affection_prompts: dict[str, str] = {}
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


def reload_config() -> tuple[bool, str, list[str]]:
    """Reload configuration from settings files.

    Returns:
        (success, message, changed_fields) tuple.
    """
    try:
        _settings.reload()
        new_config = _get_typed_config(_AppConfig)

        # Validate critical fields haven't changed
        critical_fields = ["token", "db_url", "api_id", "api_hash", "session_name"]
        for field in critical_fields:
            if getattr(new_config, field) != getattr(app_config, field):
                return False, f"Cannot reload: {field} changed (requires restart)", []

        # Reload powermem config if path is set
        if new_config.agent_powermem_config_path:
            with open(new_config.agent_powermem_config_path, encoding="utf-8") as f:
                new_config.agent_powermem_config = json.load(f)
            if new_config.agent_powermem_config is None:
                return False, "Loaded powermem_config is None", []
            if new_config.agent_powermem_custom_fact_extraction_prompt is not None:
                new_config.agent_powermem_config["custom_fact_extraction_prompt"] = (
                    new_config.agent_powermem_custom_fact_extraction_prompt
                )

        # Diff and update app_config in-place to preserve references
        changed: list[str] = []
        for field in _AppConfig.model_fields:
            old_val = getattr(app_config, field)
            new_val = getattr(new_config, field)
            if old_val != new_val:
                changed.append(field)
            setattr(app_config, field, new_val)

        return True, "Configuration reloaded successfully", changed
    except Exception as e:
        return False, f"Reload failed: {e}", []


__all__ = ["app_config", "reload_config"]
