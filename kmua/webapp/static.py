"""Static hosting for the built Mini App bundle.

Vite emits hashed asset filenames plus a single `index.html` entry point. Assets
are served with long-lived immutable caching; `index.html` must never be cached,
otherwise clients keep booting a stale bundle that references deleted assets.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from kmua.config import app_config
from kmua.logger import logger

_DEFAULT_DIST = Path(__file__).resolve().parent / "dist"

# Telegram renders Mini Apps inside an iframe on the web clients, so framing must
# stay allowed - but only from Telegram's own origins.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "form-action 'none'; "
    "frame-ancestors https://web.telegram.org https://*.telegram.org"
)


def resolve_static_dir() -> Path:
    """Return the configured bundle directory, or the packaged default."""
    if app_config.webapp_static_dir:
        return Path(app_config.webapp_static_dir).expanduser().resolve()
    return _DEFAULT_DIST


def static_bundle_exists() -> bool:
    """Whether a built bundle with an entry point is present."""
    return (resolve_static_dir() / "index.html").is_file()


class SpaStaticFiles(StaticFiles):
    """StaticFiles that falls back to `index.html` for client-side routes.

    The panel uses history-based routing, so a deep link like `/admin/users` has no
    file behind it and must still boot the SPA.

    Starlette signals a missing file by raising `HTTPException(404)` rather than
    returning a 404 response, so the fallback has to catch the exception - checking
    the status code alone silently never fires.

    Three things deliberately do not fall back:

    - `api/*`, so an unknown endpoint answers with the JSON error shape. This mount
      is a catch-all at the root, so without the check a typo'd endpoint would
      return the app shell with status 200 and the client would try to parse HTML.
    - anything with a file extension, so a missing hashed asset stays a 404 rather
      than becoming a confusing parse error in the console.
    - `health` and `ready`, for the same reason as the API.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not _is_client_route(path):
                raise
            response = await super().get_response("index.html", scope)
        return _apply_headers(response, path)


# Paths owned by the server, never by the client-side router.
_SERVER_PREFIXES = ("api/", "health", "ready")


def _is_client_route(path: str) -> bool:
    """Whether a missing path should boot the SPA instead of returning 404."""
    if path.startswith(_SERVER_PREFIXES):
        return False
    # Client routes are extensionless (`admin/users`); files are not (`favicon.ico`).
    return "." not in path.rsplit("/", 1)[-1]


def _apply_headers(response: Response, path: str) -> Response:
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    if path.startswith("assets/") and isinstance(response, FileResponse):
        # Hashed filenames: safe to cache forever.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def mount_static(app: FastAPI) -> bool:
    """Mount the SPA at the app root. Returns False when no bundle is present."""
    static_dir = resolve_static_dir()
    if not (static_dir / "index.html").is_file():
        logger.warning(
            f"webapp: no frontend bundle at {static_dir}, serving API only. "
            "Run `pnpm build` in webapp/ or set webapp_static_dir."
        )
        return False

    app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="webapp")
    logger.debug(f"webapp: serving frontend bundle from {static_dir}")
    return True


async def add_api_security_headers(request: Request, call_next):
    """Attach hardening headers to API responses.

    `X-Frame-Options` is deliberately omitted: it has no per-origin allowlist, so
    setting it would break the Telegram web clients that embed the panel.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response
