"""Telegram initData verification and session tokens.

Two distinct steps, deliberately kept apart:

1. `verify_init_data` proves a request really came from a Telegram client, by
   recomputing the HMAC that Telegram signed the launch parameters with.
2. `issue_token` / `decode_token` carry that proof across subsequent requests.

Session tokens intentionally hold no privileges - only the user id. Roles are
resolved per request (see `deps.py`), so promoting or demoting somebody takes
effect immediately instead of when their token happens to expire.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

import jwt

from kmua.config import app_config
from kmua.webapp.errors import ErrorCode, unauthorized

_JWT_ALGORITHM = "HS256"
_JWT_ISSUER = "kmua"

# Telegram's fixed HMAC salt for Mini App initData.
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
_WEBAPP_SALT = b"WebAppData"


@dataclass(slots=True)
class InitDataUser:
    """The `user` object embedded in initData."""

    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_bot: bool = False
    is_premium: bool = False
    photo_url: str | None = None

    @property
    def full_name(self) -> str:
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name


@dataclass(slots=True)
class InitData:
    """Verified launch parameters."""

    user: InitDataUser
    auth_date: int
    start_param: str | None = None
    chat_instance: str | None = None
    query_id: str | None = None
    raw: dict[str, str] | None = None


_MIN_SECRET_BYTES = 32
_warned_about_short_secret = False


def _jwt_secret() -> str:
    """Return the signing secret, deriving one from the bot token if unset.

    Deriving keeps zero-config deployments working while never using the bot
    token itself as the signing key - a leaked panel token must not be usable
    against the Bot API.
    """
    configured = app_config.webapp_jwt_secret
    if configured:
        _warn_if_secret_is_weak(configured)
        return configured
    return hmac.new(
        app_config.token.encode(), b"kmua-webapp-jwt", hashlib.sha256
    ).hexdigest()


def _warn_if_secret_is_weak(secret: str) -> None:
    """Warn once when a hand-written secret is too short to matter for HS256."""
    global _warned_about_short_secret
    if _warned_about_short_secret:
        return
    if len(secret.encode()) < _MIN_SECRET_BYTES:
        from kmua.logger import logger

        logger.warning(
            f"webapp: webapp_jwt_secret is shorter than {_MIN_SECRET_BYTES} bytes, "
            "which weakens session tokens. Leave it empty to derive a strong key "
            "from the bot token, or set at least 32 random bytes."
        )
        _warned_about_short_secret = True


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(_WEBAPP_SALT, bot_token.encode(), hashlib.sha256).digest()


def _data_check_string(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{key}={value}" for key, value in sorted(pairs))


def verify_init_data(
    init_data_raw: str,
    *,
    bot_token: str | None = None,
    ttl: int | None = None,
    now: float | None = None,
) -> InitData:
    """Verify a raw initData query string and return its parsed contents.

    Raises `ApiError` (401) when the signature does not match, the payload is
    malformed, or `auth_date` is older than the configured TTL.
    """
    if not init_data_raw or not init_data_raw.strip():
        raise unauthorized(ErrorCode.INIT_DATA_MISSING, "initData is empty")

    token = bot_token if bot_token is not None else app_config.token
    if not token:
        raise unauthorized(ErrorCode.INIT_DATA_INVALID, "Bot token is not configured")

    try:
        pairs = parse_qsl(init_data_raw, strict_parsing=True, keep_blank_values=True)
    except ValueError as e:
        raise unauthorized(
            ErrorCode.INIT_DATA_MALFORMED, "initData is not a query string"
        ) from e

    received_hash: str | None = None
    payload_pairs: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == "hash":
            received_hash = value
            continue
        # Bot-token validation signs every received field except `hash`. The
        # Ed25519 third-party flow is different: it also excludes `signature`.
        payload_pairs.append((key, value))

    if not received_hash:
        raise unauthorized(ErrorCode.INIT_DATA_MALFORMED, "initData has no hash")

    expected = hmac.new(
        _secret_key(token),
        _data_check_string(payload_pairs).encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise unauthorized(ErrorCode.INIT_DATA_INVALID, "initData signature mismatch")

    fields = dict(payload_pairs)

    raw_auth_date = fields.get("auth_date")
    if not raw_auth_date or not raw_auth_date.isdigit():
        raise unauthorized(ErrorCode.INIT_DATA_MALFORMED, "initData has no auth_date")
    auth_date = int(raw_auth_date)

    max_age = app_config.webapp_initdata_ttl if ttl is None else ttl
    if max_age > 0:
        current = time.time() if now is None else now
        if current - auth_date > max_age:
            raise unauthorized(ErrorCode.INIT_DATA_EXPIRED, "initData has expired")

    user = _parse_user(fields.get("user"))

    return InitData(
        user=user,
        auth_date=auth_date,
        start_param=fields.get("start_param"),
        chat_instance=fields.get("chat_instance"),
        query_id=fields.get("query_id"),
        raw=fields,
    )


def _parse_user(raw_user: str | None) -> InitDataUser:
    if not raw_user:
        raise unauthorized(ErrorCode.INIT_DATA_MALFORMED, "initData has no user")
    try:
        data: Any = json.loads(raw_user)
    except json.JSONDecodeError as e:
        raise unauthorized(
            ErrorCode.INIT_DATA_MALFORMED, "initData user is not valid JSON"
        ) from e
    if not isinstance(data, dict):
        raise unauthorized(
            ErrorCode.INIT_DATA_MALFORMED, "initData user is not an object"
        )

    user_id = data.get("id")
    first_name = data.get("first_name")
    if not isinstance(user_id, int) or not isinstance(first_name, str):
        raise unauthorized(
            ErrorCode.INIT_DATA_MALFORMED, "initData user is missing id or first_name"
        )

    return InitDataUser(
        id=user_id,
        first_name=first_name,
        last_name=data.get("last_name") or None,
        username=data.get("username") or None,
        language_code=data.get("language_code") or None,
        is_bot=bool(data.get("is_bot", False)),
        is_premium=bool(data.get("is_premium", False)),
        photo_url=data.get("photo_url") or None,
    )


def issue_token(user_id: int, *, ttl: int | None = None) -> tuple[str, int]:
    """Sign a session token for `user_id`. Returns `(token, expires_at)`."""
    lifetime = app_config.webapp_jwt_ttl if ttl is None else ttl
    issued_at = int(time.time())
    expires_at = issued_at + lifetime
    payload = {
        "sub": str(user_id),
        "iss": _JWT_ISSUER,
        "iat": issued_at,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)
    return token, expires_at


def decode_token(token: str) -> int:
    """Validate a session token and return its user id.

    The algorithm is pinned to HS256 so a forged header cannot downgrade
    verification (the classic `alg: none` confusion attack).
    """
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[_JWT_ALGORITHM],
            issuer=_JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise unauthorized(ErrorCode.TOKEN_EXPIRED, "Session has expired") from e
    except jwt.InvalidTokenError as e:
        raise unauthorized(ErrorCode.TOKEN_INVALID, "Session token is invalid") from e

    # `sub` is required above, so it is present - but `decode` returns an untyped
    # dict, and a token could carry any JSON value there. Narrow to `str` before
    # converting rather than letting `int()` decide what it accepts.
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise unauthorized(ErrorCode.TOKEN_INVALID, "Session subject is invalid")
    try:
        return int(subject)
    except ValueError as e:
        raise unauthorized(ErrorCode.TOKEN_INVALID, "Session subject is invalid") from e


def parse_start_param_chat_id(start_param: str | None) -> int | None:
    """Decode a `?startapp=c<digits>` deep link into a chat id.

    This is a navigation hint only: the caller still has to pass the regular
    per-chat authorization check before anything is read or written.
    """
    if not start_param or not start_param.startswith("c"):
        return None
    digits = start_param[1:]
    if not digits.isdigit():
        return None
    return -int(digits)


def build_chat_start_param(chat_id: int) -> str:
    """Encode a chat id for a `?startapp=` deep link."""
    return f"c{abs(chat_id)}"
