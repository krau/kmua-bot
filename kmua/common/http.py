"""Proxied HTTP client factory for agent model requests.

Centralises the ``httpx`` proxy wiring used by :mod:`kmua.plugins.agent.provider`
and :mod:`kmua.services.image_gen`. The factory reuses a small cache keyed by
the resolved proxy URL so that repeated ``make_chat_model`` calls (per-chat
overrides, streaming loops) do not leak ``AsyncClient`` instances.

``httpx`` handles ``http://``, ``https://`` and ``socks5://`` proxy URLs when
``httpx[socks]`` is installed (already pulled transitively via ``ddgs``; an
explicit extra is added in ``pyproject.toml`` for stability).
"""

from __future__ import annotations

import httpx

from kmua.config import app_config

# Cache: proxy URL (or "" for direct) -> httpx.AsyncClient
_clients: dict[str, httpx.AsyncClient] = {}


def _resolve_proxy(provider_proxy: str | None) -> str | None:
    """Return the effective proxy URL for the current call.

    Precedence: explicit provider ``proxy`` > global ``agent_proxy``.
    Empty strings are treated as unset.
    """
    if provider_proxy:
        stripped = provider_proxy.strip()
        if stripped:
            return stripped
    global_proxy = getattr(app_config, "agent_proxy", None)
    if global_proxy:
        stripped = str(global_proxy).strip()
        if stripped:
            return stripped
    return None


def get_agent_http_client(
    provider_proxy: str | None = None,
) -> httpx.AsyncClient | None:
    """Return a cached ``httpx.AsyncClient`` configured for the resolved proxy.

    Returns ``None`` when no proxy is configured (the caller should let
    ``pydantic-ai``/``openai`` create its own default client). Otherwise
    returns a shared client with ``proxy`` set and ``trust_env=True`` so that
    ``NO_PROXY`` / ``no_proxy`` from the environment is still honoured.

    The client is cached for the lifetime of the process and closed via
    :func:`close_agent_http_clients` (called from ``__main__.stop_bot``).
    """
    proxy = _resolve_proxy(provider_proxy)
    if proxy is None:
        return None

    # Normalise empty string already handled; use proxy as cache key directly
    # so that distinct proxies get distinct pools.
    cached = _clients.get(proxy)
    if cached is not None and not cached.is_closed:
        return cached

    # ``httpx.AsyncClient(proxy=...)`` is supported since httpx 0.24.
    # ``trust_env=True`` (default) preserves NO_PROXY handling.
    try:
        client = httpx.AsyncClient(
            proxy=proxy,
            timeout=httpx.Timeout(60.0, connect=10.0),
            trust_env=True,
        )
    except Exception as exc:  # pragma: no cover - invalid proxy URL
        # Let the caller surface the error; do not cache a broken entry.
        raise ValueError(f"Invalid proxy URL {proxy!r}: {exc}") from exc

    _clients[proxy] = client
    return client


async def close_agent_http_clients() -> None:
    """Close all cached proxied clients (idempotent)."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass


__all__ = ["close_agent_http_clients", "get_agent_http_client"]
