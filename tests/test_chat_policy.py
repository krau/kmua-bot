"""Chat policy tests — operator-controlled per-chat settings.

The agent whitelist is the first policy flag. It gates every agent entry point, so the
properties that matter are that `is_chat_allowed` reflects a panel edit without a
restart, and that only an owner can make one.

The sync-reader contract is the subtle part: `is_chat_allowed` is called from message
filters that cannot await, so it reads an in-memory mirror rather than the table. These
tests pin that writes update the mirror in the same call, and that an unloaded mirror
falls back to the config list instead of denying everything.
"""

from __future__ import annotations

import pytest

from kmua import database
from kmua.config import app_config
from kmua.database import chat_policy as store
from kmua.database.models import ChatPolicy
from kmua.plugins.agent.whitelist import is_chat_allowed
from tests.webapp_helpers import api_client, bearer, make_chat, make_user, set_owners

pytestmark = pytest.mark.usefixtures("initialised_db")

OWNER_ID = 9100001
ADMIN_ID = 9100002
PLAIN_ID = 9100003


@pytest.fixture(autouse=True)
async def clean_policy():
    """Empty the table and reset the mirror between tests."""
    rows = await database.get_chat_policies()
    for row, _ in rows:
        await database.delete_chat_policy(row.chat_id)
    store._set_agent_cache(set())
    yield
    rows = await database.get_chat_policies()
    for row, _ in rows:
        await database.delete_chat_policy(row.chat_id)


@pytest.fixture
def whitelist_mode(monkeypatch):
    monkeypatch.setattr(app_config, "agent_whitelist_mode", True, raising=False)


# ------------------------------------------------------------------ storage layer


async def test_enabling_a_chat_is_allowed_without_reloading(whitelist_mode):
    """The point of the whole change: a write is visible to the sync reader at once."""
    assert is_chat_allowed(-100900001) is False

    await database.set_chat_policy(
        -100900001, ChatPolicy(agent_allowed=True), updated_by=OWNER_ID
    )

    assert is_chat_allowed(-100900001) is True


async def test_disabling_a_chat_is_denied_without_reloading(whitelist_mode):
    await database.set_chat_policy(-100900002, ChatPolicy(agent_allowed=True))
    assert is_chat_allowed(-100900002) is True

    await database.set_chat_policy(-100900002, ChatPolicy(agent_allowed=False))

    assert is_chat_allowed(-100900002) is False


async def test_deleting_a_row_returns_to_default(whitelist_mode):
    await database.set_chat_policy(-100900003, ChatPolicy(agent_allowed=True))
    assert is_chat_allowed(-100900003) is True

    await database.delete_chat_policy(-100900003)

    assert is_chat_allowed(-100900003) is False


async def test_whitelist_mode_off_allows_every_chat():
    """With the gate off the flag is inert, however the table is populated."""
    assert app_config.agent_whitelist_mode is False
    assert is_chat_allowed(-100900005) is True


async def test_none_chat_id_is_never_allowed(whitelist_mode):
    assert is_chat_allowed(None) is False


async def test_unloaded_mirror_falls_back_to_config(whitelist_mode, monkeypatch):
    """During startup the table has not been read yet; deny-all would be wrong."""
    monkeypatch.setattr(app_config, "agent_whitelist", [-100900006], raising=False)
    store._set_agent_cache_unloaded()

    assert is_chat_allowed(-100900006) is True
    assert is_chat_allowed(-100900007) is False


async def test_policy_records_who_set_it_and_the_note():
    await database.set_chat_policy(
        -100900008,
        ChatPolicy(agent_allowed=True),
        updated_by=OWNER_ID,
        note="test group",
    )

    policy = await database.get_chat_policy(-100900008)
    rows = await database.get_chat_policies()
    row, _ = next(r for r in rows if r[0].chat_id == -100900008)

    assert policy.agent_allowed is True
    assert row.updated_by == OWNER_ID
    assert row.note == "test group"


async def test_policy_row_copies_a_known_chat_title():
    await make_chat(-100900009, title="Known Group")

    await database.set_chat_policy(-100900009, ChatPolicy(agent_allowed=True))

    rows = await database.get_chat_policies()
    row, live_title = next(r for r in rows if r[0].chat_id == -100900009)

    assert row.chat_title == "Known Group"
    assert live_title == "Known Group"


async def test_policy_row_for_an_unknown_chat_has_no_title():
    """A group can have policy set before the bot has ever seen it."""
    await database.set_chat_policy(-100900010, ChatPolicy(agent_allowed=True))

    rows = await database.get_chat_policies()
    row, live_title = next(r for r in rows if r[0].chat_id == -100900010)

    assert row.chat_title is None
    assert live_title is None


async def test_seed_only_adds_missing_ids():
    await database.set_chat_policy(-100900011, ChatPolicy(agent_allowed=True))

    seeded = await database.seed_agent_allowed_chats([-100900011, -100900012])

    assert seeded == 1
    assert await database.count_chat_policies() == 2


async def test_seed_ignores_duplicates_in_its_input():
    seeded = await database.seed_agent_allowed_chats([-100900013, -100900013])

    assert seeded == 1


async def test_deleting_an_absent_policy_reports_no_change():
    assert await database.delete_chat_policy(-100900014) is False


async def test_get_policy_for_a_chat_with_no_row_returns_defaults():
    policy = await database.get_chat_policy(-100900015)
    assert policy.agent_allowed is False


async def test_set_policy_with_absent_flags_leaves_them_alone():
    """The PUT contract: a partial write does not reset unmentioned flags."""
    await database.set_chat_policy(-100900016, ChatPolicy(agent_allowed=True))

    # A hypothetical second flag added later: setting it should not touch agent_allowed.
    current = await database.get_chat_policy(-100900016)
    assert current.agent_allowed is True

    # Re-save with agent_allowed unchanged.
    await database.set_chat_policy(-100900016, current)

    policy = await database.get_chat_policy(-100900016)
    assert policy.agent_allowed is True


# --------------------------------------------------------------------------- API


async def test_admin_can_read_policy_list(monkeypatch):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(ADMIN_ID, global_admin=True)
    await database.set_chat_policy(
        -100900020, ChatPolicy(agent_allowed=True), note="visible"
    )

    async with api_client() as client:
        response = await client.get(
            "/api/admin/chat-policies", headers=bearer(ADMIN_ID)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_whitelist_mode"] is False
    assert [e["chat_id"] for e in body["items"]] == [-100900020]
    assert body["items"][0]["policy"]["agent_allowed"] is True
    assert body["items"][0]["note"] == "visible"


async def test_owner_can_set_policy_and_response_carries_the_new_list(monkeypatch):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID)

    async with api_client() as client:
        response = await client.put(
            "/api/admin/chat-policies/-100900021",
            json={"agent_allowed": True, "note": "onboarded"},
            headers=bearer(OWNER_ID),
        )

    assert response.status_code == 200
    assert [e["chat_id"] for e in response.json()["items"]] == [-100900021]


async def test_set_policy_is_immediately_visible_to_is_chat_allowed(
    monkeypatch, whitelist_mode
):
    """End to end: the panel writes, and the agent's sync check sees it."""
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID)
    assert is_chat_allowed(-100900022) is False

    async with api_client() as client:
        response = await client.put(
            "/api/admin/chat-policies/-100900022",
            json={"agent_allowed": True, "note": None},
            headers=bearer(OWNER_ID),
        )

    assert response.status_code == 200
    assert is_chat_allowed(-100900022) is True


async def test_owner_can_delete_policy(monkeypatch, whitelist_mode):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID)
    await database.set_chat_policy(-100900023, ChatPolicy(agent_allowed=True))

    async with api_client() as client:
        response = await client.delete(
            "/api/admin/chat-policies/-100900023", headers=bearer(OWNER_ID)
        )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert is_chat_allowed(-100900023) is False


async def test_deleting_an_absent_policy_is_a_404(monkeypatch):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID)

    async with api_client() as client:
        response = await client.delete(
            "/api/admin/chat-policies/-100900025", headers=bearer(OWNER_ID)
        )

    assert response.status_code == 404


async def test_global_admin_cannot_set_policy(monkeypatch):
    """Granting the agent access to a group is a wider grant than a global admin has."""
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(ADMIN_ID, global_admin=True)

    async with api_client() as client:
        response = await client.put(
            "/api/admin/chat-policies/-100900026",
            json={"agent_allowed": True, "note": None},
            headers=bearer(ADMIN_ID),
        )

    assert response.status_code == 403
    assert await database.count_chat_policies() == 0


async def test_global_admin_cannot_delete_policy(monkeypatch):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(ADMIN_ID, global_admin=True)
    await database.set_chat_policy(-100900027, ChatPolicy(agent_allowed=True))

    async with api_client() as client:
        response = await client.delete(
            "/api/admin/chat-policies/-100900027", headers=bearer(ADMIN_ID)
        )

    assert response.status_code == 403
    assert await database.count_chat_policies() == 1


async def test_a_plain_user_cannot_read_policy_list(monkeypatch):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(PLAIN_ID)

    async with api_client() as client:
        response = await client.get(
            "/api/admin/chat-policies", headers=bearer(PLAIN_ID)
        )

    assert response.status_code == 403


async def test_unauthenticated_access_is_refused():
    async with api_client() as client:
        response = await client.get("/api/admin/chat-policies")

    assert response.status_code == 401


async def test_the_mode_flag_is_reported(monkeypatch, whitelist_mode):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(ADMIN_ID, global_admin=True)

    async with api_client() as client:
        response = await client.get(
            "/api/admin/chat-policies", headers=bearer(ADMIN_ID)
        )

    assert response.json()["agent_whitelist_mode"] is True


async def test_put_with_absent_flags_leaves_them_at_their_current_value(monkeypatch):
    """The API PUT mirrors the database: unmentioned flags are left alone."""
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID)
    await database.set_chat_policy(-100900028, ChatPolicy(agent_allowed=True))

    async with api_client() as client:
        # Hypothetical: setting a second flag without mentioning agent_allowed.
        response = await client.put(
            "/api/admin/chat-policies/-100900028",
            json={"agent_allowed": None, "note": "updated"},
            headers=bearer(OWNER_ID),
        )

    assert response.status_code == 200
    policy = await database.get_chat_policy(-100900028)
    assert policy.agent_allowed is True
