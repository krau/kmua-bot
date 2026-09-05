"""Unified IO tools: read/write/edit/list/search/delete over protocol prefixes.

Protocols:
- kmua://      read-only view of the bot's own codebase (agentfs snapshot)
- work://      sandboxed workspace: files the agent writes
- chat://      the current group: info, message history, sending quotes
- memory://    the group's long-term memory
- web://       web search
- http(s)://   web page fetching

Layout:
- protocols.py — protocol parsing and per-protocol availability (single source
  of truth shared by the call-time gate and the prepare functions)
- targets.py   — byte/line access to sandbox, workspace and persisted targets
- media.py     — Telegram media download and native image returns
- content.py   — the read-side content dispatcher
- tools.py     — the six tool functions exposed to the model
- prepares.py  — per-tool visibility mirroring availability into descriptions
"""

from ... import provider  # noqa: F401
from .. import bot, chat, code_repo, datatype, db, web, workspace  # noqa: F401
from .content import _read_chat, _read_content  # noqa: F401
from .media import _download_tme_media, _run_model_accepts_images  # noqa: F401
from .prepares import (  # noqa: F401
    prepare_delete,
    prepare_edit,
    prepare_list,
    prepare_read,
    prepare_search,
    prepare_write,
)
from .protocols import _kmua_enabled, _require, _split_target  # noqa: F401
from .targets import (  # noqa: F401
    _download_persisted,
    _session_key,
    _write_persisted,
    read_bytes,
)
from .tools import _search_web, delete, edit, list, read, search, write  # noqa: F401

__all__ = [
    "read",
    "write",
    "edit",
    "list",
    "search",
    "delete",
    "prepare_read",
    "prepare_write",
    "prepare_edit",
    "prepare_list",
    "prepare_search",
    "prepare_delete",
    "read_bytes",
]
