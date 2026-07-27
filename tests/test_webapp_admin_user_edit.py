"""Developer user-editing tests.

The affection case is the important one. `UserConfig.affection` lives in a JSON
column, but the percentile ranking is served from a separate `affection_histogram`
bucket table that only `update_user_affection` maintains. Writing the column
directly leaves the histogram stale and silently corrupts every percentile in the
bot, with nothing to notice it - so the test asserts the bucket moved.
"""

from __future__ import annotations

import pytest

from kmua import database
from kmua.database.affection import AffectionHistogram, affection_bucket
from kmua.database.db import AsyncSessionFactory
from tests.webapp_helpers import api_client, bearer, make_user, set_owners

pytestmark = pytest.mark.usefixtures("initialised_db")

OWNER_ID = 920_001
GLOBAL_ADMIN_ID = 920_002
TARGET_ID = 920_003


@pytest.fixture
async def cast(monkeypatch):
    await make_user(OWNER_ID, full_name="Owner")
    await make_user(GLOBAL_ADMIN_ID, full_name="Global Admin", global_admin=True)
    target = await make_user(TARGET_ID, full_name="Target", username="target")
    set_owners(monkeypatch, [OWNER_ID])
    # The fixtures insert rows directly, which on SQLite bypasses the histogram
    # bookkeeping (PostgreSQL has a trigger for it). Rebuild so the buckets match
    # the rows before asserting how an edit moves them.
    await database.rebuild_histogram()
    return target


async def bucket_count(bucket: int) -> int:
    async with AsyncSessionFactory() as session:
        row = await session.get(AffectionHistogram, bucket)
        return row.cnt if row else 0


async def test_owner_can_edit_coins(cast):
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"coins": 5000},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] == []
    assert {"field": "coins", "old": 144 * 16, "new": 5000} in body["changed"]

    config = await database.get_user_config(TARGET_ID)
    assert config.coins == 5000


@pytest.mark.parametrize("coins", [-144 * 16 - 1, 10**9 + 1])
async def test_coins_outside_the_allowed_range_are_rejected(cast, coins):
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"coins": coins},
        )

    assert response.status_code == 422


async def test_affection_edit_keeps_the_histogram_consistent(cast):
    """The percentile ranking depends on these buckets staying in step."""
    before = await database.get_user_config(TARGET_ID)
    old_bucket = affection_bucket(before.affection)
    new_affection = before.affection + 5000
    new_bucket = affection_bucket(new_affection)
    assert old_bucket != new_bucket, "test needs a value that crosses a bucket"

    old_bucket_before = await bucket_count(old_bucket)
    new_bucket_before = await bucket_count(new_bucket)

    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"affection": new_affection},
        )

    assert response.status_code == 200
    config = await database.get_user_config(TARGET_ID)
    assert config.affection == new_affection

    assert await bucket_count(old_bucket) == old_bucket_before - 1
    assert await bucket_count(new_bucket) == new_bucket_before + 1


async def test_global_admin_cannot_edit_coins_or_affection(cast):
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(GLOBAL_ADMIN_ID),
            json={"coins": 1, "affection": 1, "full_name": "Renamed"},
        )

    assert response.status_code == 200
    body = response.json()
    skipped = {item["field"]: item["reason"] for item in body["skipped"]}
    changed = {item["field"] for item in body["changed"]}

    # The permitted part of a mixed edit still applies.
    assert changed == {"full_name"}
    assert skipped == {
        "coins": "OWNER_REQUIRED",
        "affection": "OWNER_REQUIRED",
    }

    target = await database.get_user_by_id(TARGET_ID)
    assert target is not None and target.full_name == "Renamed"


async def test_owner_can_toggle_global_admin(cast):
    async with api_client() as client:
        granted = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"is_bot_global_admin": True},
        )
        revoked = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"is_bot_global_admin": False},
        )

    assert granted.status_code == 200
    assert granted.json()["user"]["is_bot_global_admin"] is True
    assert revoked.json()["user"]["is_bot_global_admin"] is False


async def test_an_owner_cannot_change_their_own_role(cast):
    """Guards against an operator locking themselves out of the admin roster."""
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{OWNER_ID}",
            headers=bearer(OWNER_ID),
            json={"is_bot_global_admin": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] == []
    assert body["skipped"] == [
        {"field": "is_bot_global_admin", "reason": "cannot change own role"}
    ]


async def test_an_unchanged_value_reports_no_change(cast):
    current = await database.get_user_config(TARGET_ID)

    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"coins": current.coins},
        )

    assert response.status_code == 200
    assert response.json()["changed"] == []


async def test_an_empty_patch_is_a_no_op(cast):
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}", headers=bearer(OWNER_ID), json={}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] == []
    assert body["skipped"] == []


@pytest.mark.parametrize(
    "field", ["coins", "affection", "lang", "full_name", "is_bot_global_admin"]
)
async def test_an_explicit_null_is_skipped_not_written(cast, field):
    """`null` survives exclude_unset, but no field here treats it as "clear".

    Left to reach the writers it either raises in int()/bool() or stores the
    string "None" as the user's display name.
    """
    before = await database.get_user_by_id(TARGET_ID)
    assert before is not None
    config_before = await database.get_user_config(TARGET_ID)

    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={field: None},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] == []
    assert body["skipped"] == [
        {"field": field, "reason": "null is not a valid value"}
    ]

    after = await database.get_user_by_id(TARGET_ID)
    assert after is not None
    assert after.full_name == before.full_name
    assert after.is_bot_global_admin == before.is_bot_global_admin
    config_after = await database.get_user_config(TARGET_ID)
    assert config_after.lang == config_before.lang
    assert config_after.coins == config_before.coins
    assert config_after.affection == config_before.affection


async def test_rejects_an_unknown_locale(cast):
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"lang": "nonsense"},
        )

    assert response.status_code == 422


async def test_marriage_can_only_be_cleared_not_set(cast):
    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"is_married": True},
        )

    assert response.status_code == 422


async def test_editing_is_refused_when_the_feature_is_off(cast, monkeypatch):
    from kmua.config import app_config

    monkeypatch.setattr(app_config, "webapp_admin_edit_user", False)

    async with api_client() as client:
        response = await client.patch(
            f"/api/admin/users/{TARGET_ID}",
            headers=bearer(OWNER_ID),
            json={"coins": 7},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "FEATURE_DISABLED"


async def test_editing_a_missing_user_is_a_404(cast):
    async with api_client() as client:
        response = await client.patch(
            "/api/admin/users/987654321",
            headers=bearer(OWNER_ID),
            json={"coins": 7},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


async def test_changes_are_written_to_the_audit_log(cast):
    """Privileged edits must leave a trail."""
    records: list[str] = []

    from kmua.webapp import audit

    class _Sink:
        @staticmethod
        def warning(message: str) -> None:
            records.append(message)

    original = audit.logger
    audit.logger = _Sink  # type: ignore[assignment]
    try:
        async with api_client() as client:
            response = await client.patch(
                f"/api/admin/users/{TARGET_ID}",
                headers=bearer(OWNER_ID),
                json={"full_name": "Audited Name"},
            )
    finally:
        audit.logger = original

    assert response.status_code == 200
    assert len(records) == 1
    entry = records[0]
    assert "admin.user.update" in entry
    assert str(OWNER_ID) in entry
    assert "Audited Name" in entry
