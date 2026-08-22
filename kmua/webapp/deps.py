"""Request-scoped identity and authorization.

Roles are resolved on every request instead of being baked into the session
token. That costs one indexed primary-key lookup and buys correctness: a demoted
admin loses access immediately rather than when their token expires.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from kmua import common, database
from kmua.config import app_config
from kmua.database.models import ChatData, UserData
from kmua.logger import logger
from kmua.webapp.auth import decode_token
from kmua.webapp.errors import ErrorCode, forbidden, not_found, unauthorized

# auto_error=False so a missing header produces our own error shape instead of
# FastAPI's default {"detail": ...}.
_bearer = HTTPBearer(auto_error=False)


class Role:
    """Role names as sent to the frontend."""

    __slots__ = ()

    USER = "user"
    GLOBAL_ADMIN = "global_admin"
    OWNER = "owner"


@dataclass(slots=True)
class SessionUser:
    """The authenticated caller."""

    id: int
    data: UserData
    roles: list[str] = field(default_factory=list)

    @property
    def is_owner(self) -> bool:
        return Role.OWNER in self.roles

    @property
    def is_global_admin(self) -> bool:
        return Role.GLOBAL_ADMIN in self.roles

    @property
    def is_admin(self) -> bool:
        """Owner or global admin: allowed into the developer panel."""
        return self.is_owner or self.is_global_admin

    @property
    def full_name(self) -> str:
        return self.data.full_name


def resolve_roles(user: UserData) -> list[str]:
    roles = [Role.USER]
    if user.is_bot_global_admin:
        roles.append(Role.GLOBAL_ADMIN)
    if user.id in app_config.owners:
        roles.append(Role.OWNER)
    return roles


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> SessionUser:
    """Authenticate the bearer token and load the caller's current record."""
    if credentials is None or not credentials.credentials:
        raise unauthorized(ErrorCode.TOKEN_MISSING, "Authorization header is missing")

    user_id = decode_token(credentials.credentials)
    user_data = await database.get_user_by_id(user_id)
    if user_data is None:
        # The token is well-formed but the account is gone.
        raise unauthorized(ErrorCode.USER_NOT_FOUND, "Session user no longer exists")

    return SessionUser(id=user_id, data=user_data, roles=resolve_roles(user_data))


CurrentUser = Annotated[SessionUser, Depends(get_current_user)]


async def require_bot_admin(user: CurrentUser) -> SessionUser:
    """Allow owners and global admins only."""
    if not user.is_admin:
        raise forbidden(ErrorCode.ADMIN_REQUIRED, "Bot admin rights are required")
    return user


async def require_owner(user: CurrentUser) -> SessionUser:
    """Allow owners only."""
    if not user.is_owner:
        raise forbidden(ErrorCode.OWNER_REQUIRED, "Bot owner rights are required")
    return user


RequireAdmin = Annotated[SessionUser, Depends(require_bot_admin)]
RequireOwner = Annotated[SessionUser, Depends(require_owner)]


@dataclass(slots=True)
class ChatContext:
    """A chat the caller is allowed to manage."""

    chat: ChatData
    user: SessionUser

    @property
    def id(self) -> int:
        return self.chat.id


async def require_chat_admin(
    user: CurrentUser,
    chat_id: Annotated[int, Path(description="Telegram chat id, negative")],
) -> ChatContext:
    """Authorize the caller to manage the bot in `chat_id`.

    Group ids are negative; rejecting non-negative ids up front stops a private
    chat id or a user id from being probed through this path.
    """
    if chat_id >= 0:
        raise not_found(ErrorCode.CHAT_NOT_FOUND, "Not a group chat id")

    chat = await database.get_chat_by_id(chat_id)
    if chat is None:
        raise not_found(ErrorCode.CHAT_NOT_FOUND, "Chat not found")

    # Owners and global admins manage every chat; skip the Telegram round trip.
    if user.is_admin:
        return ChatContext(chat=chat, user=user)

    try:
        # A wedged bot session must not hang this dependency (and with it the
        # whole panel route) past a bounded window.
        allowed = await asyncio.wait_for(
            common.can_user_manage_bot_in_chat(user.id, chat_id), timeout=10
        )
    except Exception as e:
        # A Telegram lookup failure must not read as "authorized".
        logger.warning(f"webapp: chat admin check failed for {user.id}@{chat_id}: {e}")
        raise forbidden(
            ErrorCode.CHAT_ADMIN_REQUIRED, "Could not verify chat permissions"
        ) from e

    if not allowed:
        raise forbidden(
            ErrorCode.CHAT_ADMIN_REQUIRED, "Bot admin rights in this chat are required"
        )
    return ChatContext(chat=chat, user=user)


ChatAdminCtx = Annotated[ChatContext, Depends(require_chat_admin)]


def client_key(request: Request, suffix: str | int = "") -> str:
    """Build a rate-limit key from the peer address plus an optional discriminator.

    `request.client` already reflects `X-Forwarded-For` when uvicorn is started
    with `proxy_headers` and a trusted-host list. Parsing the header here instead
    would let any client spoof its way into a fresh rate-limit bucket.
    """
    host = request.client.host if request.client else "unknown"
    return f"{host}:{suffix}" if suffix != "" else host
