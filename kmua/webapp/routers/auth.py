"""Session establishment from Telegram launch parameters."""

from __future__ import annotations

from fastapi import APIRouter, Request

from kmua import database
from kmua.webapp import auth
from kmua.webapp.deps import client_key, resolve_roles
from kmua.webapp.errors import ErrorCode, unauthorized
from kmua.webapp.ratelimit import auth_limiter
from kmua.webapp.schemas import AuthRequest, AuthResponse, SessionUserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthResponse)
async def authenticate(request: Request, payload: AuthRequest) -> AuthResponse:
    """Exchange verified Telegram initData for a session token."""
    # Rate-limit before the HMAC so a flood of forged payloads stays cheap.
    auth_limiter.check(client_key(request, "auth"))

    init_data = auth.verify_init_data(payload.init_data_raw)

    if init_data.user.is_bot:
        raise unauthorized(ErrorCode.FORBIDDEN, "Bots cannot use the panel")

    user_data = await database.upsert_user(_as_pyrogram_user(init_data.user))
    token, expires_at = auth.issue_token(user_data.id)

    return AuthResponse(
        token=token,
        expires_at=expires_at,
        user=SessionUserOut(
            id=user_data.id,
            full_name=user_data.full_name,
            username=user_data.username,
            is_bot_global_admin=user_data.is_bot_global_admin,
        ),
        roles=resolve_roles(user_data),
        start_chat_id=auth.parse_start_param_chat_id(init_data.start_param),
    )


def _as_pyrogram_user(user: auth.InitDataUser):
    """Adapt initData's user object to what `upsert_user` reads.

    `upsert_user` only touches id, username, full_name, is_bot and is_real_user,
    so a light stand-in avoids constructing a full pyrogram User (which would need
    a client bound for its own reasons).
    """
    from pyrogram.types import User

    return User(
        id=user.id,
        is_bot=user.is_bot,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
    )
