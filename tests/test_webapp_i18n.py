"""Locale files are data, but duplicate JSON keys silently overwrite each other."""

from __future__ import annotations

import json
from pathlib import Path

LOCALE_DIR = Path(__file__).parents[1] / "webapp" / "src" / "i18n"


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def test_locales_have_no_duplicate_keys() -> None:
    for locale in sorted(LOCALE_DIR.glob("*.json")):
        with locale.open(encoding="utf-8") as source:
            json.load(source, object_pairs_hook=_reject_duplicate_keys)
