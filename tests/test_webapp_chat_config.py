"""Group configuration endpoint tests.

The chat config is a single JSON column that the inline /config keyboard also
writes. These tests pin the two properties that keep the two writers compatible:
validation rejects out-of-range values before they reach the column, and a config
save never disturbs the separately-edited title permissions.
"""

from __future__ import annotations

import pytest

from kmua import database
from tests.webapp_helpers import (
    api_client,
    bearer,
    join_chat,
    make_chat,
    make_user,
    set_owners,
    stub_chat_member_lookup,
)

pytestmark = pytest.mark.usefixtures("initialised_db")

ADMIN_ID = 910_001
CHAT_ID = -100_910_001


def valid_config(**overrides) -> dict:
    payload = {
        "waifu_enabled": True,
        "delete_events_enabled": False,
        "unpin_channel_pin_enabled": False,
        "quote_probability": 0.05,
        "quote_pin_message": True,
        "greeting": "Welcome ${user}",
        "ai_reply": True,
        "ai_reply_other_bots_enabled": False,
        "ai_comment": False,
        "setu_enabled": True,
        "convert_b23_enabled": True,
        "parse_links_enabled": True,
        "parse_artwork_enabled": True,
        "parse_sites_enabled": {},
        "pick_bottle_enabled": True,
        "group_memory_enabled": True,
        "parse_wechat_enabled": True,
        "rss_agent_summary": False,
        "rss_agent_broadcast": False,
        "verify_enabled": False,
        "verify_strategy": "all",
        "verify_method": "math_easy",
        "verify_max_attempts": 3,
        "verify_timeout_seconds": 120,
        "verify_fail_action": "kick",
        "lang": "zh-CN",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def chat_admin(monkeypatch):
    admin = await make_user(ADMIN_ID, full_name="Config Admin")
    chat = await make_chat(CHAT_ID, title="Config Chat")
    await join_chat(admin, chat, bot_admin=True)
    set_owners(monkeypatch, [])
    stub_chat_member_lookup(monkeypatch)
    return admin, chat


async def test_saves_a_full_config_document(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(waifu_enabled=False, quote_probability=0.5),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["waifu_enabled"] is False
    assert body["quote_probability"] == 0.5

    stored = await database.get_chat_config(CHAT_ID)
    assert stored.waifu_enabled is False
    assert stored.quote_probability == 0.5


@pytest.mark.parametrize("probability", [-0.1, 1.1, 2, -1])
async def test_rejects_an_out_of_range_probability(chat_admin, probability):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(quote_probability=probability),
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


async def test_rejects_an_overlong_greeting(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(greeting="x" * 1025),
        )

    assert response.status_code == 422


async def test_accepts_a_greeting_at_the_limit(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(greeting="x" * 1024),
        )

    assert response.status_code == 200


async def test_rejects_an_unknown_locale(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(lang="klingon"),
        )

    assert response.status_code == 422


async def test_rejects_unknown_fields(chat_admin):
    """Extra keys are refused so a client typo cannot silently do nothing."""
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(waifu_enable=False),
        )

    assert response.status_code == 422


async def test_blank_greeting_becomes_null(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(greeting="   "),
        )

    assert response.status_code == 200
    assert response.json()["greeting"] is None


async def test_saving_the_config_preserves_title_permissions(chat_admin):
    """The two pages edit the same JSON column; neither may clobber the other."""
    async with api_client() as client:
        await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_pin_messages": True}},
        )
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(),
        )

    assert response.status_code == 200
    assert response.json()["title_permissions"]["can_pin_messages"] is True


async def test_title_permissions_replace_the_whole_set(chat_admin):
    async with api_client() as client:
        await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_pin_messages": True, "can_invite_users": True}},
        )
        response = await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_pin_messages": True}},
        )

    assert response.status_code == 200
    permissions = response.json()["title_permissions"]
    assert permissions["can_pin_messages"] is True
    assert permissions["can_invite_users"] is False


async def test_rejects_an_unknown_title_permission(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/title-permissions",
            headers=bearer(ADMIN_ID),
            json={"permissions": {"can_launch_missiles": True}},
        )

    assert response.status_code == 422


async def test_config_read_matches_what_the_bot_sees(chat_admin):
    """The panel and the bot must agree on the stored config."""
    async with api_client() as client:
        await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(ai_reply=False, lang="en"),
        )
        response = await client.get(f"/api/chats/{CHAT_ID}", headers=bearer(ADMIN_ID))

    assert response.status_code == 200
    from_api = response.json()["config"]
    from_bot = await database.get_chat_config(CHAT_ID)

    assert from_api["ai_reply"] == from_bot.ai_reply is False
    assert from_api["lang"] == from_bot.lang == "en"


# ---------------------------------------------------------------- verification


async def test_accepts_first_message_strategy(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(verify_strategy="first_message"),
        )

    assert response.status_code == 200
    assert response.json()["verify_strategy"] == "first_message"


async def test_accepts_math_hard_method(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(verify_method="math_hard"),
        )

    assert response.status_code == 200
    assert response.json()["verify_method"] == "math_hard"


async def test_saves_verify_settings(chat_admin):
    """The config document round-trips verification settings."""
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(
                verify_enabled=True,
                verify_method="sticker",
                verify_fail_action="ban",
                verify_max_attempts=5,
                verify_timeout_seconds=300,
            ),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["verify_enabled"] is True
    assert body["verify_method"] == "sticker"
    assert body["verify_fail_action"] == "ban"
    assert body["verify_max_attempts"] == 5
    assert body["verify_timeout_seconds"] == 300

    stored = await database.get_chat_config(CHAT_ID)
    assert stored.verify_enabled is True
    assert stored.verify_method == "sticker"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verify_strategy", "sometimes"),
        ("verify_method", "captcha"),
        ("verify_fail_action", "warn"),
    ],
)
async def test_rejects_an_unknown_strategy_method_or_fail_action(
    chat_admin, field, value
):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(**{field: value}),
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verify_max_attempts", 0),
        ("verify_max_attempts", 11),
        ("verify_timeout_seconds", 29),
        ("verify_timeout_seconds", 601),
    ],
)
async def test_rejects_out_of_range_attempts_and_timeout(chat_admin, field, value):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(**{field: value}),
        )

    assert response.status_code == 422


async def test_config_payload_rejects_verify_questions(chat_admin):
    """The question bank has its own endpoint; the config document must not carry it."""
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(verify_questions=[{"question": "?", "answers": ["a"]}]),
        )

    assert response.status_code == 422


async def test_verify_questions_replace_the_whole_set(chat_admin):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/verify-questions",
            headers=bearer(ADMIN_ID),
            json={
                "questions": [
                    {"question": "Q1?", "options": ["a", "b"], "answers": ["a"]},
                    {
                        "question": "Q2?",
                        "options": [" b ", " c ", "b"],
                        "answers": [" b ", "c"],
                        "select": "any",
                    },
                    {"question": "  Q3?  ", "options": ["d", "e"], "answers": [" e "]},
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert [q["question"] for q in body["questions"]] == ["Q1?", "Q2?", "Q3?"]
        assert body["questions"][1]["options"] == ["b", "c"]  # 去重
        assert body["questions"][1]["answers"] == ["b", "c"]  # 答案去重, 支持多选
        assert body["questions"][1]["select"] == "any"  # 任选其一模式回读
        assert body["questions"][0]["select"] == "all"  # 缺省全选
        assert body["questions"][2]["options"] == ["d", "e"]
        assert body["questions"][2]["answers"] == ["e"]  # 答案 trim 后仍在选项中

        response = await client.put(
            f"/api/chats/{CHAT_ID}/verify-questions",
            headers=bearer(ADMIN_ID),
            json={
                "questions": [
                    {"question": "Only?", "options": ["x", "y"], "answers": ["x"]}
                ]
            },
        )
        assert response.status_code == 200
        assert len(response.json()["questions"]) == 1

    stored = await database.get_chat_config(CHAT_ID)
    assert len(stored.verify_questions) == 1
    assert stored.verify_questions[0]["question"] == "Only?"


async def test_saving_config_preserves_verify_questions(chat_admin):
    """The two pages edit the same JSON column; neither may clobber the other."""
    async with api_client() as client:
        await client.put(
            f"/api/chats/{CHAT_ID}/verify-questions",
            headers=bearer(ADMIN_ID),
            json={
                "questions": [
                    {
                        "question": "Keep me?",
                        "options": ["yes", "no"],
                        "answers": ["yes"],
                    }
                ]
            },
        )
        response = await client.put(
            f"/api/chats/{CHAT_ID}/config",
            headers=bearer(ADMIN_ID),
            json=valid_config(),
        )

    assert response.status_code == 200
    assert response.json()["verify_questions"] == [
        {
            "question": "Keep me?",
            "options": ["yes", "no"],
            "answers": ["yes"],
            "select": "all",
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"questions": [{"question": "   ", "options": ["a", "b"], "answers": ["a"]}]},
        {"questions": [{"question": "Q?", "options": ["a"], "answers": ["a"]}]},
        {"questions": [{"question": "Q?", "options": ["  ", " "], "answers": ["a"]}]},
        {"questions": [{"question": "Q?", "options": ["a", "b"], "answers": ["c"]}]},
        {"questions": [{"question": "Q?", "options": ["a", "b"], "answers": ["  "]}]},
        {
            "questions": [
                {"question": "x" * 201, "options": ["a", "b"], "answers": ["a"]}
            ]
        },
        {
            "questions": [
                {"question": "Q?", "options": ["ok" * 51, "b"], "answers": ["ok" * 51]}
            ]
        },
        {
            "questions": [{"question": "Q?", "options": ["a", "b"], "answers": ["a"]}]
            * 201
        },
        {
            "questions": [
                {
                    "question": "Q?",
                    "options": ["a", "b"],
                    "answers": ["a"],
                    "select": "both",
                }
            ]
        },
    ],
)
async def test_rejects_invalid_verify_questions(chat_admin, payload):
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/verify-questions",
            headers=bearer(ADMIN_ID),
            json=payload,
        )

    assert response.status_code == 422


async def test_accepts_limits_at_the_boundary(chat_admin):
    """200 题、题目 200 字、选项 100 字是合法上限, 应被接受。"""
    question = {"question": "x" * 200, "options": ["a", "y" * 100], "answers": ["a"]}
    payload = {"questions": [question] * 200}
    async with api_client() as client:
        response = await client.put(
            f"/api/chats/{CHAT_ID}/verify-questions",
            headers=bearer(ADMIN_ID),
            json=payload,
        )

    assert response.status_code == 200
    assert len(response.json()["questions"]) == 200
    assert response.json()["questions"][0]["question"] == "x" * 200
