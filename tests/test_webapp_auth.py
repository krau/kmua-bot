"""initData verification and session token tests.

These cover the boundary the whole panel rests on: everything downstream trusts
that a request carrying a session token really came from the Telegram user it
claims. Each negative case here is an authentication bypass if it regresses.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from kmua.webapp import auth
from kmua.webapp.errors import ApiError, ErrorCode

BOT_TOKEN = "123456:test-bot-token-for-unit-tests"


def make_init_data(
    *,
    token: str = BOT_TOKEN,
    user: dict | None = None,
    auth_date: int | None = None,
    start_param: str | None = None,
    extra: dict[str, str] | None = None,
    tamper_hash: str | None = None,
    omit_hash: bool = False,
) -> str:
    """Build a signed initData string the way a Telegram client would."""
    fields: dict[str, str] = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAEtest",
    }
    if user is not None or user is None:
        fields["user"] = json.dumps(
            user
            if user is not None
            else {"id": 424242, "first_name": "Kmua", "username": "kmua_test"},
            separators=(",", ":"),
        )
    if start_param:
        fields["start_param"] = start_param
    if extra:
        fields.update(extra)

    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    if omit_hash:
        return urlencode(fields)
    return urlencode({**fields, "hash": tamper_hash or signature})


def test_accepts_a_correctly_signed_payload():
    init_data = make_init_data(start_param="c1852445173")

    result = auth.verify_init_data(init_data, bot_token=BOT_TOKEN)

    assert result.user.id == 424242
    assert result.user.username == "kmua_test"
    assert result.start_param == "c1852445173"


def test_builds_full_name_from_both_name_parts():
    init_data = make_init_data(
        user={"id": 1, "first_name": "Miya", "last_name": "Neko"}
    )

    result = auth.verify_init_data(init_data, bot_token=BOT_TOKEN)

    assert result.user.full_name == "Miya Neko"


def test_rejects_a_tampered_hash():
    init_data = make_init_data(tamper_hash="0" * 64)

    with pytest.raises(ApiError) as exc:
        auth.verify_init_data(init_data, bot_token=BOT_TOKEN)

    assert exc.value.code == ErrorCode.INIT_DATA_INVALID
    assert exc.value.status_code == 401


def test_rejects_a_payload_signed_with_another_token():
    """A signature from a different bot must not authenticate against this one."""
    init_data = make_init_data(token="999:someone-elses-token")

    with pytest.raises(ApiError) as exc:
        auth.verify_init_data(init_data, bot_token=BOT_TOKEN)

    assert exc.value.code == ErrorCode.INIT_DATA_INVALID


def test_rejects_modified_fields_even_though_hash_is_present():
    """Changing any field after signing must invalidate the payload."""
    signed = make_init_data(user={"id": 1, "first_name": "Low"})
    forged = signed.replace("%22id%22%3A1", "%22id%22%3A2")

    with pytest.raises(ApiError) as exc:
        auth.verify_init_data(forged, bot_token=BOT_TOKEN)

    assert exc.value.code == ErrorCode.INIT_DATA_INVALID


def test_rejects_an_expired_auth_date():
    init_data = make_init_data(auth_date=int(time.time()) - 3600)

    with pytest.raises(ApiError) as exc:
        auth.verify_init_data(init_data, bot_token=BOT_TOKEN, ttl=300)

    assert exc.value.code == ErrorCode.INIT_DATA_EXPIRED


def test_accepts_an_old_auth_date_when_ttl_is_disabled():
    init_data = make_init_data(auth_date=int(time.time()) - 86400)

    result = auth.verify_init_data(init_data, bot_token=BOT_TOKEN, ttl=0)

    assert result.user.id == 424242


def test_rejects_a_missing_hash():
    init_data = make_init_data(omit_hash=True)

    with pytest.raises(ApiError) as exc:
        auth.verify_init_data(init_data, bot_token=BOT_TOKEN)

    assert exc.value.code == ErrorCode.INIT_DATA_MALFORMED


def test_rejects_an_empty_payload():
    with pytest.raises(ApiError) as exc:
        auth.verify_init_data("   ", bot_token=BOT_TOKEN)

    assert exc.value.code == ErrorCode.INIT_DATA_MISSING


def test_rejects_a_payload_without_a_user():
    fields = {"auth_date": str(int(time.time()))}
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    init_data = urlencode({**fields, "hash": signature})

    with pytest.raises(ApiError) as exc:
        auth.verify_init_data(init_data, bot_token=BOT_TOKEN)

    assert exc.value.code == ErrorCode.INIT_DATA_MALFORMED


def test_includes_the_ed25519_signature_field_in_the_hmac():
    """Bot-token HMAC signs every parameter except `hash`, including `signature`."""
    init_data = make_init_data(extra={"signature": "a" * 86})

    result = auth.verify_init_data(init_data, bot_token=BOT_TOKEN)

    assert result.user.id == 424242

    tampered = init_data.replace("signature=" + "a" * 86, "signature=" + "b" * 86)
    with pytest.raises(ApiError) as exc:
        auth.verify_init_data(tampered, bot_token=BOT_TOKEN)

    assert exc.value.code == ErrorCode.INIT_DATA_INVALID


def test_session_token_round_trips():
    token, expires_at = auth.issue_token(4242)

    assert auth.decode_token(token) == 4242
    assert expires_at > time.time()


def test_rejects_an_expired_session_token():
    token, _ = auth.issue_token(4242, ttl=-1)

    with pytest.raises(ApiError) as exc:
        auth.decode_token(token)

    assert exc.value.code == ErrorCode.TOKEN_EXPIRED


def test_rejects_a_token_signed_with_the_wrong_key():
    import jwt

    forged = jwt.encode(
        {"sub": "1", "iss": "kmua", "iat": 0, "exp": int(time.time()) + 60},
        "not-the-real-secret",
        algorithm="HS256",
    )

    with pytest.raises(ApiError) as exc:
        auth.decode_token(forged)

    assert exc.value.code == ErrorCode.TOKEN_INVALID


def test_rejects_an_unsigned_token():
    """`alg: none` must never be accepted, however well-formed the claims are."""
    import jwt

    unsigned = jwt.encode(
        {"sub": "1", "iss": "kmua", "iat": 0, "exp": int(time.time()) + 60},
        key="",
        algorithm="none",
    )

    with pytest.raises(ApiError) as exc:
        auth.decode_token(unsigned)

    assert exc.value.code == ErrorCode.TOKEN_INVALID


def test_rejects_a_token_from_another_issuer():
    import jwt

    from kmua.webapp.auth import _jwt_secret

    foreign = jwt.encode(
        {
            "sub": "1",
            "iss": "somebody-else",
            "iat": 0,
            "exp": int(time.time()) + 60,
        },
        _jwt_secret(),
        algorithm="HS256",
    )

    with pytest.raises(ApiError) as exc:
        auth.decode_token(foreign)

    assert exc.value.code == ErrorCode.TOKEN_INVALID


def test_rejects_a_token_missing_required_claims():
    import jwt

    from kmua.webapp.auth import _jwt_secret

    incomplete = jwt.encode({"sub": "1", "iss": "kmua"}, _jwt_secret(), algorithm="HS256")

    with pytest.raises(ApiError) as exc:
        auth.decode_token(incomplete)

    assert exc.value.code == ErrorCode.TOKEN_INVALID


@pytest.mark.parametrize(
    ("start_param", "expected"),
    [
        ("c1852445173", -1852445173),
        ("c1", -1),
        (None, None),
        ("", None),
        ("nonsense", None),
        ("cabc", None),
        ("1852445173", None),
    ],
)
def test_parses_chat_deep_links(start_param, expected):
    assert auth.parse_start_param_chat_id(start_param) == expected


def test_chat_deep_link_round_trips():
    chat_id = -1001852445173
    encoded = auth.build_chat_start_param(chat_id)

    assert auth.parse_start_param_chat_id(encoded) == chat_id
