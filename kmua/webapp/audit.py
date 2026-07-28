"""Audit trail for privileged panel actions.

Anything an owner or global admin does that changes state is recorded here. The
records go to the normal loguru sink at WARNING level so they survive in the
rotated log files and stand out from routine traffic.

Values are stringified and truncated: an audit line proves who changed what and
when, it is not a place to mirror user content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from kmua.logger import logger

_MAX_VALUE_LEN = 200


@dataclass(slots=True)
class FieldChange:
    """A single field transition, as reported back to the client."""

    field: str
    old: Any
    new: Any

    def as_dict(self) -> dict[str, Any]:
        return {"field": self.field, "old": self.old, "new": self.new}


@dataclass(slots=True)
class SkippedField:
    """A field that was submitted but not applied, and why."""

    field: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "reason": self.reason}


def _trim(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_VALUE_LEN:
        return value[:_MAX_VALUE_LEN] + "…"
    return value


def record(
    *,
    action: str,
    actor_id: int,
    actor_roles: list[str],
    target: str | int | None = None,
    changes: list[FieldChange] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write one audit entry."""
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "action": action,
        "actor_id": actor_id,
        "actor_roles": actor_roles,
    }
    if target is not None:
        entry["target"] = target
    if changes:
        entry["changes"] = [
            {
                "field": change.field,
                "old": _trim(change.old),
                "new": _trim(change.new),
            }
            for change in changes
        ]
    if extra:
        entry["extra"] = {key: _trim(value) for key, value in extra.items()}

    logger.warning(f"webapp.audit {json.dumps(entry, ensure_ascii=False)}")
