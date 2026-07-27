"""Pagination and search helpers shared by the panel queries.

Kept separate from the domain modules so listing behaviour (clamping, offsets,
case-insensitive matching across dialects) is defined once.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy

from kmua.config import runtime_config

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@dataclass(slots=True)
class Page[T]:
    """One slice of a listing, plus the total for the client's pager."""

    items: Sequence[T]
    total: int
    page: int
    size: int

    @property
    def has_more(self) -> bool:
        return self.page * self.size < self.total


def normalize_page(page: int, size: int) -> tuple[int, int]:
    """Clamp caller-supplied paging into a safe range."""
    safe_page = max(1, page)
    safe_size = min(MAX_PAGE_SIZE, max(1, size))
    return safe_page, safe_size


def offset_for(page: int, size: int) -> int:
    return (page - 1) * size


def text_match(column: Any, query: str) -> sqlalchemy.ColumnElement[bool]:
    """Case-insensitive substring match that behaves the same on every backend.

    PostgreSQL's ILIKE is native. SQLite's LIKE is already case-insensitive for
    ASCII but not for non-ASCII, so both sides are lowered explicitly - which
    matters here because most kmua display names are CJK.
    """
    pattern = f"%{query.lower()}%"
    if runtime_config.db_is_postgres:
        return column.ilike(f"%{query}%")
    return sqlalchemy.func.lower(column).like(pattern)


def parse_id_query(query: str) -> int | None:
    """Interpret a search box entry as a Telegram id, if it looks like one."""
    candidate = query.strip()
    if not candidate:
        return None
    if candidate.startswith("-"):
        digits = candidate[1:]
        return -int(digits) if digits.isdigit() else None
    return int(candidate) if candidate.isdigit() else None
