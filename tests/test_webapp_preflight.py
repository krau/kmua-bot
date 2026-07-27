"""Startup preflight tests.

The panel must never be the reason the bot fails to start. When its configuration is
wrong it degrades to serving health checks only and says why - these tests pin each
of those decisions, because a regression here turns a typo in settings.toml into a
bot that will not come up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kmua.config import app_config
from kmua.webapp.server import _panel_preflight


@pytest.fixture
def panel_config(monkeypatch, tmp_path):
    """A configuration that passes preflight, for tests to break one field at a time."""
    bundle = tmp_path / "dist"
    bundle.mkdir()
    (bundle / "index.html").write_text("<!doctype html>", encoding="utf-8")

    monkeypatch.setattr(app_config, "webapp", True)
    monkeypatch.setattr(app_config, "webapp_url", "https://panel.example.test")
    monkeypatch.setattr(app_config, "webapp_static_dir", str(bundle))
    monkeypatch.setattr(app_config, "webapp_allow_origins", [])
    return bundle


def test_a_complete_configuration_enables_the_panel(panel_config):
    assert _panel_preflight() is True


def test_the_panel_stays_off_when_not_enabled(panel_config, monkeypatch):
    monkeypatch.setattr(app_config, "webapp", False)

    assert _panel_preflight() is False


def test_a_missing_url_disables_the_panel(panel_config, monkeypatch):
    monkeypatch.setattr(app_config, "webapp_url", "")

    assert _panel_preflight() is False


def test_a_plain_http_url_disables_the_panel(panel_config, monkeypatch):
    """Telegram refuses to open a Mini App over HTTP, so this can only be a mistake."""
    monkeypatch.setattr(app_config, "webapp_url", "http://panel.example.test")

    assert _panel_preflight() is False


def test_a_missing_bundle_disables_the_panel(panel_config, monkeypatch):
    monkeypatch.setattr(app_config, "webapp_static_dir", "/nonexistent/dist")

    assert _panel_preflight() is False


def test_a_directory_without_an_entry_point_disables_the_panel(panel_config):
    """An empty dist directory is a failed build, not a valid bundle."""
    (panel_config / "index.html").unlink()

    assert _panel_preflight() is False


def test_a_missing_bundle_is_tolerated_when_dev_origins_are_set(
    panel_config, monkeypatch
):
    """With `pnpm dev` serving the frontend, an API-only backend is the intent."""
    monkeypatch.setattr(app_config, "webapp_static_dir", "/nonexistent/dist")
    monkeypatch.setattr(app_config, "webapp_allow_origins", ["http://localhost:5173"])

    assert _panel_preflight() is True


def test_the_packaged_bundle_directory_is_used_by_default(panel_config, monkeypatch):
    """An empty webapp_static_dir must resolve to the path the Dockerfile fills."""
    from kmua.webapp.static import resolve_static_dir

    monkeypatch.setattr(app_config, "webapp_static_dir", "")

    expected = Path(__file__).resolve().parent.parent / "kmua" / "webapp" / "dist"
    assert resolve_static_dir() == expected
