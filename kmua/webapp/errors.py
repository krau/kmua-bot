"""Error codes and exception handlers for the Mini App API.

The API answers failures with a stable machine-readable ``code`` plus an English
fallback ``message``. The frontend renders the user-facing text from the code, so
adding a language never requires a backend change.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from kmua.logger import logger


class ErrorCode:
    """Stable error codes shared with the frontend."""

    __slots__ = ()

    # auth
    INIT_DATA_MISSING = "INIT_DATA_MISSING"
    INIT_DATA_MALFORMED = "INIT_DATA_MALFORMED"
    INIT_DATA_INVALID = "INIT_DATA_INVALID"
    INIT_DATA_EXPIRED = "INIT_DATA_EXPIRED"
    TOKEN_MISSING = "TOKEN_MISSING"
    TOKEN_INVALID = "TOKEN_INVALID"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"

    # authorization
    FORBIDDEN = "FORBIDDEN"
    OWNER_REQUIRED = "OWNER_REQUIRED"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"
    CHAT_ADMIN_REQUIRED = "CHAT_ADMIN_REQUIRED"

    # resources
    USER_NOT_FOUND = "USER_NOT_FOUND"
    CHAT_NOT_FOUND = "CHAT_NOT_FOUND"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"

    # request
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    COOLDOWN = "COOLDOWN"
    CONFLICT = "CONFLICT"
    FEATURE_DISABLED = "FEATURE_DISABLED"

    # domain
    NOT_MARRIED = "NOT_MARRIED"
    INSUFFICIENT_COINS = "INSUFFICIENT_COINS"
    GIFT_NOT_FOUND = "GIFT_NOT_FOUND"
    GIFT_ALREADY_SENT = "GIFT_ALREADY_SENT"
    TELEGRAM_ERROR = "TELEGRAM_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(Exception):
    """Domain failure carrying an error code and an HTTP status."""

    def __init__(
        self,
        code: str,
        message: str = "",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code
        self.details = details

    def to_response(self) -> JSONResponse:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return JSONResponse(payload, status_code=self.status_code)


def unauthorized(code: str, message: str = "") -> ApiError:
    return ApiError(code, message, status.HTTP_401_UNAUTHORIZED)


def forbidden(code: str, message: str = "") -> ApiError:
    return ApiError(code, message, status.HTTP_403_FORBIDDEN)


def not_found(code: str, message: str = "") -> ApiError:
    return ApiError(code, message, status.HTTP_404_NOT_FOUND)


_STATUS_TO_CODE = {
    status.HTTP_401_UNAUTHORIZED: ErrorCode.TOKEN_MISSING,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
}


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every failure shares one response shape."""

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Field paths help the frontend highlight the offending input; raw input
        # values are dropped so user data never bounces back through the error.
        fields = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": error.get("type", ""),
                "msg": error.get("msg", ""),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            {
                "code": ErrorCode.VALIDATION_FAILED,
                "message": "Request validation failed",
                "details": {"fields": fields},
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = exc.detail if isinstance(exc.detail, str) else code
        return JSONResponse(
            {"code": code, "message": message}, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback, return only the code: internals stay server-side.
        logger.opt(exception=exc).error(
            f"webapp: unhandled error on {request.method} {request.url.path}"
        )
        return JSONResponse(
            {"code": ErrorCode.INTERNAL_ERROR, "message": "Internal server error"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
