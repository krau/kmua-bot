"""Redaction for the runtime configuration snapshot.

The developer panel shows what the bot is actually running with, which means
walking a config object that also holds the bot token, database DSN and every
provider API key.

This module is an allowlist, not a denylist: a field is exposed only if it is
named here. Adding a new secret to `_AppConfig` therefore cannot leak by
default - the failure mode of forgetting to update this file is a missing row in
the panel, not a published credential.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kmua.config import app_config

_REDACTED = "***"
_NOT_SET = None

# Fields safe to show verbatim, grouped the way the panel renders them.
_PUBLIC_FIELDS: dict[str, tuple[str, ...]] = {
    "base": (
        "session_name",
        "api_id",
        "lang",
        "nickname",
        "log_level",
        "log_retention_days",
        "automigrate",
        "debug",
        "use_ipv6",
        "pg_pgroonga",
    ),
    "webapp": (
        "webapp",
        "webapp_host",
        "webapp_port",
        "webapp_url",
        "webapp_short_name",
        "webapp_menu_button",
        "webapp_jwt_ttl",
        "webapp_initdata_ttl",
        "webapp_allow_origins",
        "webapp_static_dir",
        "webapp_admin_edit_user",
    ),
    "monitoring": (
        "loop_monitor_enabled",
        "loop_monitor_interval",
        "loop_monitor_threshold",
        "session_health_enabled",
        "session_health_interval",
        "session_health_timeout",
        "session_health_threshold",
        "session_health_cooldown",
        "session_health_stale",
        "session_health_restart_timeout",
    ),
    "agent": (
        "agent",
        "agent_model",
        "agent_model_multimodal",
        "agent_model_small",
        "agent_struct_model",
        "agent_context_window_tokens",
        "agent_context_compress_ratio",
        "agent_compaction_keep_messages",
        "agent_compaction_clear_tool_results",
        "agent_compaction_keep_pairs",
        "agent_compaction_summarize",
        "agent_compaction_summary_instruction",
        "agent_multimodal",
        "agent_streaming",
        "agent_multimodal_inputs",
        "agent_multimodal_max_items",
        "agent_extra_tools",
        "agent_model_timeout",
        "agent_small_model_timeout",
        "agent_run_timeout",
        "agent_webfetch_timeout",
        "agent_whitelist_mode",
        "agent_group_memory",
        "agent_cross_group_memory",
        "agent_follow_up",
        "agent_sticker_memory",
        "agent_code_awareness",
        "agent_periodic_sticker_interval",
        "agent_periodic_reaction_interval",
    ),
    "services": (
        "redis",
        "redis_endpoint",
        "redis_port",
        "redis_db",
        "btts",
        "btts_api_url",
        "manyacg_api_url",
        "manyacg_channel",
        "manyacg_bot",
        "manyacg_setu_cd",
        "manyacg_hybrid_search",
        "aniobjcut",
        "aniobjcut_api_url",
        "infographic",
        "infographic_api_url",
        "avatar_change_enabled",
        "avatar_change_interval",
    ),
    "economy": (
        "cost_user_change_waifu_base",
        "cost_user_change_waifu_pow",
        "cost_throw_bottle_base",
        "cost_throw_bottle_pow",
        "cost_pick_bottle_base",
        "cost_pick_bottle_pow",
        "coin_add_chance_on_message",
        "coin_daily_add_interval",
        "coin_daily_add_count",
    ),
}

# Secrets: the panel shows only whether they are configured.
_SECRET_FIELDS: tuple[str, ...] = (
    "token",
    "api_hash",
    "db_url",
    "jobstore_db_url",
    "webapp_jwt_secret",
    "redis_password",
    "btts_api_key",
    "manyacg_api_key",
    "aniobjcut_api_key",
    "infographic_api_key",
    "agent_crawl_api_token",
)


def _plain(value: Any) -> Any:
    """Coerce a config value into something JSON-serialisable."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _secret_state(value: Any) -> str | None:
    """Describe a secret without revealing it."""
    if value is None or value == "":
        return _NOT_SET
    return _REDACTED


def config_snapshot() -> dict[str, Any]:
    """Build the redacted runtime configuration view."""
    groups: dict[str, dict[str, Any]] = {}
    for group, fields in _PUBLIC_FIELDS.items():
        groups[group] = {
            field: _plain(getattr(app_config, field))
            for field in fields
            if hasattr(app_config, field)
        }

    secrets = {
        field: _secret_state(getattr(app_config, field, None))
        for field in _SECRET_FIELDS
    }

    # Providers: names and endpoints are useful for debugging, keys never are.
    providers = {
        name: {
            "url": provider.url,
            "type": provider.type,
            "key": _secret_state(provider.key),
        }
        for name, provider in app_config.agent_providers.items()
    }

    return {
        "groups": groups,
        "secrets": secrets,
        "agent_providers": providers,
        "owners_count": len(app_config.owners),
    }
