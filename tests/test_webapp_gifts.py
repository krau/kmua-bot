"""Gift shop boundaries unique to the Mini App."""

from __future__ import annotations

import pytest

from tests.webapp_helpers import api_client, bearer, make_user

pytestmark = pytest.mark.usefixtures("initialised_db")

USER_ID = 900_010


@pytest.fixture
async def user():
    return await make_user(USER_ID, full_name="Gift User")


async def test_internal_sentinel_gift_cannot_be_bought(user):
    """The enum's fallback value is for corrupted data, never a shop item."""
    async with api_client() as client:
        response = await client.post(
            "/api/me/gifts/buy",
            headers=bearer(USER_ID),
            json={"gift_id": "otherworldly_flower"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "GIFT_NOT_FOUND"
