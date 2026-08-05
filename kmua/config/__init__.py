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
    #
    # Deprecated: these fields are kept as aliases for the `webapp_*` settings
    # below. The HTTP server is now provided by `kmua.webapp` (FastAPI), which
    # serves /health and /ready with identical semantics. When `webapp_host` /
    # `webapp_port` are left at their defaults, these values are used instead.
    health_check_enabled: bool = False
    health_check_host: str = "localhost"
    health_check_port: int = 8180

    # Telegram Mini App management panel.
    #
    # The panel and the health check endpoints share a single FastAPI app on a
    # single port. When `webapp` is false only /health and /ready are served, so
    # container health checks keep working with the panel disabled.
    webapp: bool = False
    webapp_host: str = "0.0.0.0"
    webapp_port: int = 8180
    # Public HTTPS base URL of the panel. Required when `webapp` is enabled:
    # Telegram refuses to open Mini Apps over plain HTTP.
    webapp_url: str = ""
    # Mini App short name registered via BotFather (/newapp). Used to build the
    # direct link that carries group context: t.me/<bot>/<short_name>?startapp=...
    webapp_short_name: str = "panel"
    # Set the chat menu button to open the panel.
    webapp_menu_button: bool = True
    # HS256 secret for session tokens. Derived from the bot token when empty.
    webapp_jwt_secret: str = ""
    webapp_jwt_ttl: int = 21600  # 6 hours
    # Max age of Telegram initData, in seconds. Guards against replay.
    webapp_initdata_ttl: int = 300
    # CORS origins. Empty means same-origin only; only set this for local dev.
    webapp_allow_origins: list[str] = []
    # Addresses whose X-Forwarded-For header is trusted, for rate limiting and logs.
    # Defaults to loopback, which is right when the reverse proxy runs on the same
    # host. Widen it only for the proxy's actual address: trusting "*" while the
    # port is reachable directly lets any client forge its way past the limiter.
    webapp_trusted_proxies: list[str] = ["127.0.0.1", "::1"]
    # Static asset directory. Defaults to kmua/webapp/dist when empty.
    webapp_static_dir: str = ""
    # Master switch for editing user records from the developer panel.
    webapp_admin_edit_user: bool = True

    # event loop lag monitor: detects when the single asyncio event loop is
    # blocked (the root cause of "bot freezes, no logs, no response"). When the
    # measured scheduling lag exceeds the threshold, a warning is logged together
    # with stack traces of the currently running tasks so the culprit await/call
    # can be identified.
    loop_monitor_enabled: bool = True
    loop_monitor_interval: float = 1.0  # how often to sample lag (seconds)
    loop_monitor_threshold: float = 1.0  # warn when lag exceeds this (seconds)

    # Telegram session health monitor: periodically probes the main session
    # with a lightweight API call; if it fails repeatedly (zombie session),
    # force-restarts the session to restore connectivity. This works around
    # a recovery gap in kurigram where a silently-dropped TCP connection
    # leaves the session stuck without auto-reconnect.
    session_health_enabled: bool = True
    session_health_interval: float = 60.0  # seconds between checks
    session_health_timeout: float = 15.0  # probe invoke timeout
    session_health_threshold: int = 3  # consecutive failures before restart
    session_health_cooldown: float = 60.0  # min seconds between restarts
    # Hard cap for a forced session.restart(); a hung restart (kurigram can
    # block inside stop() on its single crypto thread) must not block the
    # monitor forever.
    session_health_restart_timeout: float = 90.0
    # If no update arrives within this many seconds, the recv path is
    # considered dead (half-open TCP) and a restart is forced.
    session_health_stale: float = 300.0
    # Hard bound (seconds) for one job on a session's crypto executor
    # (pack/unpack/encrypt/decrypt). kurigram awaits those with no timeout:
    # when the queue backs up, a handler stuck on one of them freezes the
    # dispatcher and the session goes deaf while the process stays alive.
    # Timeouts surface as TimeoutError (an OSError subclass), which triggers
    # kurigram's own recovery (ping failure -> session restart).
    session_crypto_timeout: float = 15.0

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

    # infographic-api https://github.com/krau/infographic-api
    infographic: bool = False
    infographic_api_url: str = "http://localhost:3000"
    infographic_api_key: str | None = None

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
    # Per-model pydantic-ai ModelSettings overrides: temperature, top_p,
    # max_tokens, thinking (minimal/low/medium/high/xhigh), openai_reasoning_effort,
    # extra_body for provider-native params, ... Empty dict = model defaults.
    # Keys are forwarded verbatim as ModelSettings; unknown keys are ignored.
    agent_model_options: dict[str, Any] = {}
    agent_model_multimodal_options: dict[str, Any] = {}
    agent_model_small_options: dict[str, Any] = {}
    agent_struct_model_options: dict[str, Any] = {}
    # Conversation compaction: cheap passes first (clear old tool results),
    # an LLM summary only if the history still does not fit. The threshold is
    # the model's context window times the trigger ratio; 0 window disables
    # compaction.
    agent_context_window_tokens: int = 128_000
    agent_context_compress_ratio: float = 0.8
    agent_compaction_keep_messages: int = 20
    agent_compaction_clear_tool_results: bool = True
    agent_compaction_keep_pairs: int = 3
    agent_compaction_summarize: bool = True
    # Single-part clamp threshold as a fraction of the context window; scales
    # with the window so the guard stays correct when the model changes.
    agent_clamp_max_part_ratio: float = 0.4
    # Instruction for the in-place summary call (runs on the conversation's
    # own model and system prompt; only this wording is customizable).
    agent_compaction_summary_instruction: str = (
        "Summarize the conversation above into a structured handoff summary "
        "for continuing the conversation later.\n"
        "IMPORTANT: If the conversation ends with an unanswered question or a "
        "request awaiting the user's response, you MUST preserve that exact "
        "question/request.\n"
        "Use this format (omit sections that are not applicable):\n"
        "## Goal\n"
        "[What the user wants; list multiple if the conversation covers "
        "different topics]\n"
        "## Constraints & Preferences\n"
        "- [Constraints or preferences the user stated]\n"
        "## Progress\n"
        "### Done\n"
        "- [x] [Completed items]\n"
        "### In Progress\n"
        "- [ ] [Current work]\n"
        "### Blocked\n"
        "- [Issues preventing progress]\n"
        "## Key Decisions\n"
        "- **[Decision]**: [Brief rationale]\n"
        "## Next Steps\n"
        "1. [Ordered next actions]\n"
        "## Critical Context\n"
        "- [Important data, pending questions, references; keep who said "
        "what, with sender names and ids exactly as labeled - never merge "
        "two speakers' words]\n"
        "## Additional Notes\n"
        "[Anything else important, including how the user addresses you]\n"
        "Output ONLY the structured summary; NEVER continue the "
        "conversation, NEVER respond to questions in it. Keep sections "
        "concise. Preserve exact names, ids, dates, links, preferences, and "
        "distinctive phrasing. Write in the same language as the "
        "conversation."
    )
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
    agent_extra_tools: list[str] = ["websearch", "webfetch"]
    # crawl4ai API server for JS-rendered pages (e.g. docker run crawl4ai)
    # if not set, js=True requests will return an error
    agent_crawl_api_url: str | None = None
    agent_crawl_api_token: str | None = None
    agent_crawl_api_timeout: int = 60
    # Agent model call timeouts (seconds) - 0 means no timeout
    agent_model_timeout: int = 0  # Main model timeout (0 = no timeout)
    agent_small_model_timeout: int = 10  # Small model timeout for quick tasks
    agent_download_timeout: int = 30  # Download media timeout (0 = no timeout)
    # Overall wall-clock timeout for a single agent run (the whole iter loop,
    # including all tool calls and streaming). Prevents a stuck model/tool call
    # from blocking a dispatcher worker indefinitely. 0 = no timeout.
    agent_run_timeout: int = 600
    # Max seconds a streaming reply keeps editing its message before the bot
    # stops updating it (the final text is still delivered).
    agent_streaming_max_time: int = 300
    # Timeout for a single webfetch (_fetch_http via crawl4ai). 0 = no timeout.
    agent_webfetch_timeout: int = 45
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
    agent_periodic_sticker_interval: int = 0
    agent_periodic_reaction_interval: int = 0
    # Code self-awareness: allow agent to read its own codebase to understand other features
    agent_code_awareness: bool = True
    # Custom file patterns to exclude from code repository (in addition to default security exclusions)
    # Example: ["*.md", "docs/**/*", "tests/**/*"]
    agent_code_exclude_patterns: list[str] = []

    # Agent workspace: sandboxed files the agent can write and send as documents
    agent_workspace_enabled: bool = True
    # Local session files (shell sandbox dirs, workspace databases) not
    # touched for this many days are removed by the daily cleanup job; 0
    # disables the sweep. Persisted files (Telegram-backed) are exempt.
    agent_workspace_retention_days: int = 30

    # Agent shell: run commands in a landlock sandbox (landrun).
    # The shell works in a per-session real directory; files are moved in and
    # out via work:// references by trusted bot code. Disabled by default.
    agent_shell_enabled: bool = False
    agent_shell_timeout: int = 30
    agent_shell_concurrency: int = 2
    # Chats where the shell tool is available; empty = not available anywhere.
    # Private chats use their positive user id, groups their negative id, so
    # one list covers both. Still gated by agent_shell_enabled and the global
    # agent whitelist.
    agent_shell_allowed_chats: list[int] = []
    # Outbound TCP ports allowed from the sandbox; empty = no network.
    agent_shell_network_ports: list[int] = [80, 443]
    agent_landrun_path: str = "/usr/local/bin/landrun"

    # experimental, maybe removed in the future
    agent_whitelist_mode: bool = False
    agent_whitelist: list[int] = []
    agent_channel_comment_prompt: str = "评论这条频道的帖子"

    # Mask credentials (API keys, tokens, private keys) out of tool returns
    # and agent replies before they reach the model or the chat. User input
    # is deliberately left untouched.
    agent_secret_masking: bool = True
    # Tool returns over this many characters are reduced before they persist
    # in history (re-sent on every later model request otherwise). 0 disables.
    agent_tool_output_limit: int = 10_000
    # Character budget for the reduced tool return (head+tail clamp), used as
    # the fallback when spill mode cannot write.
    agent_tool_output_max_chars: int = 4_000
    # Spill mode (default): the full payload is persisted to a local store and
    # the model gets a read_tool_result handle to page/search the original
    # losslessly; truncation only kicks in if the store write fails. False =
    # pure truncation, no read-back.
    agent_tool_output_spill: bool = True
    # Per-run usage ceilings for the main agent (pydantic-ai UsageLimits);
    # 0 disables an individual limit. The ceilings are deliberately generous
    # (5x the earlier values): long multi-step tasks routinely exceed a
    # request count of 10, and the request limit binds before the tool-call
    # budget does.
    agent_usage_request_limit: int = 50
    agent_usage_tool_calls_limit: int = 150
    agent_usage_total_tokens_limit: int = 600_000
    ############################################################################
    agent_prompt: str = """"""
    agent_group_prompt: str = """"""
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
    # Cap concurrent avatar network refreshes (get_chat + download_media), so a
    # burst of cache misses (quote/waifu hot paths) cannot flood the Telegram
    # session with parallel file downloads.
    avatar_refresh_concurrency: int = 3
    # Hard timeout for one avatar refresh. Failures are remembered for
    # avatar_refresh_retry_after seconds so hot paths fall back to the cached/
    # default avatar instead of retrying a dead session on every call.
    avatar_refresh_timeout: float = 30.0
    avatar_refresh_retry_after: float = 10 * 60

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

    # RSS subscription push.
    #
    # Whitelist mode is ON by default: polling arbitrary URLs on a chat's behalf is an
    # outbound-request grant, so a chat needs an explicit `rss_allowed` policy row
    # (set by an owner in the panel) before it can subscribe. Turning this off lets
    # every chat subscribe.
    rss_enabled: bool = True
    rss_whitelist_mode: bool = True
    # Minutes between polls of every active feed.
    rss_interval: int = pydantic.Field(default=30, ge=1, le=1440)
    # Minimum minutes between agent broadcasts to one chat (per-chat switch:
    # ChatConfig.rss_agent_broadcast).
    rss_agent_broadcast_interval: int = pydantic.Field(default=30, ge=1, le=1440)
    # FxEmbed-compatible API base for native Twitter/X parsing
    # (default: public FxTwitter instance; self-hosted workers can replace it).
    fxembed_api_url: str = "https://api.fxtwitter.com"


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

_LEGACY_HEALTH_ALIASES = {
    "webapp_host": "health_check_host",
    "webapp_port": "health_check_port",
}
"""Deprecated `health_check_*` keys mapped to the `webapp_*` keys replacing them."""

_legacy_health_keys_used: list[str] = []


def _apply_legacy_health_aliases(
    config: _AppConfig, settings_obj: Any = None
) -> list[str]:
    """Let deprecated `health_check_*` settings feed the new `webapp_*` fields.

    A deprecated key only wins when the user has not set the replacement key, so
    an explicit `webapp_port` always takes precedence. Returns the deprecated
    keys that were actually applied, so the caller can warn about them once.
    """
    if settings_obj is None:
        settings_obj = _settings

    applied: list[str] = []
    for new_field, legacy_field in _LEGACY_HEALTH_ALIASES.items():
        if settings_obj.exists(new_field):
            continue
        if not settings_obj.exists(legacy_field):
            continue
        setattr(config, new_field, getattr(config, legacy_field))
        applied.append(legacy_field)
    return applied


app_config = _get_typed_config(_AppConfig)
_legacy_health_keys_used = _apply_legacy_health_aliases(app_config)

if app_config.agent and app_config.agent_powermem_config_path:
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
        _apply_legacy_health_aliases(new_config)

        # Validate critical fields haven't changed
        critical_fields = [
            "token",
            "db_url",
            "api_id",
            "api_hash",
            "session_name",
            # Rebinding the HTTP listener needs a restart.
            "webapp_host",
            "webapp_port",
        ]
        for field in critical_fields:
            if getattr(new_config, field) != getattr(app_config, field):
                return False, f"Cannot reload: {field} changed (requires restart)", []

        # Reload powermem config if path is set
        if new_config.agent and new_config.agent_powermem_config_path:
            with open(new_config.agent_powermem_config_path, encoding="utf-8") as f:
                new_config.agent_powermem_config = json.load(f)
            if new_config.agent_powermem_config is None:
                return False, "Loaded powermem_config is None", []
            if new_config.agent_powermem_custom_fact_extraction_prompt is not None:
                new_config.agent_powermem_config["custom_fact_extraction_prompt"] = (
                    new_config.agent_powermem_custom_fact_extraction_prompt
                )
        elif not new_config.agent:
            new_config.agent_powermem_config = None

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
