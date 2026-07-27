"""Panel deep-link tests.

The link is the only way into a group's settings from inside that group: Telegram will
not hand a `web_app` button its launch parameters outside a private chat, so a group has
to use the `t.me/<bot>/<app>?startapp=` form instead.

These cover the two things that can silently break it - the URL shape, and the guards
that must return nothing rather than a half-built link when the panel is not configured.
"""

from __future__ import annotations

from unittest.mock import patch

from kmua.config import app_config
from kmua.plugins import panel
from kmua.webapp.auth import build_chat_start_param, parse_start_param_chat_id


class _FakeMe:
    def __init__(self, username: str | None) -> None:
        self.username = username


def _with_client(username: str | None):
    """Patch the module-level client lookup `panel` performs."""
    from kmua.bot import client as real_client

    return patch.object(real_client, "me", _FakeMe(username) if username else None)


def test_builds_a_deep_link_for_a_group():
    with _with_client("kmua_test_bot"):
        url = panel.chat_panel_url(-1001852445173)

    assert url == "https://t.me/kmua_test_bot/panel?startapp=c1001852445173"


def test_link_round_trips_through_the_verifier():
    """The panel must decode the chat id the link encoded."""
    chat_id = -1001852445173

    with _with_client("kmua_test_bot"):
        url = panel.chat_panel_url(chat_id)

    assert url is not None
    start_param = url.split("startapp=")[1]
    assert parse_start_param_chat_id(start_param) == chat_id
    assert start_param == build_chat_start_param(chat_id)


def test_no_link_without_a_bot_username():
    """Before the client is connected there is no username to build a link from."""
    with _with_client(None):
        assert panel.chat_panel_url(-100123) is None
        assert panel.panel_available() is False


def test_no_link_when_the_panel_is_disabled():
    with _with_client("kmua_test_bot"), patch.object(app_config, "webapp", False):
        assert panel.chat_panel_url(-100123) is None
        assert panel.panel_available() is False


def test_no_link_without_a_public_url():
    with _with_client("kmua_test_bot"), patch.object(app_config, "webapp_url", ""):
        assert panel.chat_panel_url(-100123) is None


def test_no_link_without_a_short_name():
    """The short name is what BotFather registered; a link without it goes nowhere."""
    with (
        _with_client("kmua_test_bot"),
        patch.object(app_config, "webapp_short_name", ""),
    ):
        assert panel.chat_panel_url(-100123) is None


def test_button_carries_the_link_and_a_label():
    with _with_client("kmua_test_bot"):
        button = panel.chat_panel_button(-1001852445173, "zh-CN")

    assert button is not None
    assert button.url is not None
    assert button.url.endswith("?startapp=c1001852445173")
    assert button.text


def test_no_button_when_no_link():
    with _with_client(None):
        assert panel.chat_panel_button(-100123, "zh-CN") is None
