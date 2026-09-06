from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic_ai.embeddings import (
    EmbeddingModel,
    EmbeddingResult,
    EmbeddingSettings,
)
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.embeddings.result import EmbedInputType
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import check_allow_model_requests
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from kmua.config import ProviderConfig, app_config

# Import video-capable model
from .video_model import VideoCapableOpenAIChatModel

_EMBED_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _get_http_client_for_provider(provider_name: str):  # type: ignore[no-untyped-def]
    """Return a proxied httpx.AsyncClient for *provider_name* if configured."""
    from kmua.common.http import get_agent_http_client

    cfg = _get_provider(provider_name)
    return get_agent_http_client(cfg.proxy)


def make_model_settings(
    options: dict[str, Any] | None,
) -> ModelSettings | None:
    """Build pydantic-ai ModelSettings from a config options dict.

    Returns None for an empty/absent dict so callers can skip the argument
    entirely and keep model defaults.
    """
    if not options:
        return None
    return ModelSettings(**options)


def _parse_spec(spec: str) -> tuple[str, str]:
    """Split 'provider/model' into (provider_name, model_name).

    A bare 'model_name' (no slash) returns ("default", "model_name").
    """
    if "/" in spec:
        provider, _, model = spec.partition("/")
        return provider.strip(), model.strip()
    return "default", spec.strip()


def _get_provider(name: str) -> ProviderConfig:
    providers = app_config.agent_providers
    if name in providers:
        return providers[name]
    raise ValueError(
        f"Provider {name!r} not found in agent_providers. "
        f"Available: {list(providers.keys())}"
    )


def _ollama_root(url: str) -> str:
    """Normalize an Ollama URL to the server root.

    Accepts ``http://host:11434``, ``http://host:11434/`` and the
    OpenAI-compatible base ``http://host:11434/v1``; all yield the root that
    the native ``/api/*`` endpoints are served from.
    """
    url = url.strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3].rstrip("/")
    return url


def _openai_base_url(cfg: ProviderConfig) -> str:
    """Return the OpenAI-compatible base URL for *cfg*.

    Ollama providers are configured with the server root; the legacy
    ``/v1`` prefix is restored so Chat Completions / Responses clients and
    ``/v1/embeddings`` keep working.
    """
    if cfg.api_type == "ollama":
        return _ollama_root(cfg.url) + "/v1"
    return cfg.url


def _make_openai_provider(provider_name: str) -> OpenAIProvider:
    cfg = _get_provider(provider_name)
    http_client = _get_http_client_for_provider(provider_name)
    if http_client is not None:
        return OpenAIProvider(
            base_url=_openai_base_url(cfg), api_key=cfg.key, http_client=http_client
        )
    return OpenAIProvider(base_url=_openai_base_url(cfg), api_key=cfg.key)


def make_chat_model(
    spec: str,
) -> VideoCapableOpenAIChatModel | OpenAIResponsesModel:
    """Build a chat model from a 'provider/model' spec.

    The model type is determined by the provider's api_type field:
    - "chat_completions" (default): returns VideoCapableOpenAIChatModel
    - "responses": returns OpenAIResponsesModel
    """
    provider_name, model_name = _parse_spec(spec)
    cfg = _get_provider(provider_name)
    openai_provider = _make_openai_provider(provider_name)
    if cfg.type == "responses":
        return OpenAIResponsesModel(
            model_name=model_name,
            provider=openai_provider,
        )
    return VideoCapableOpenAIChatModel(
        model_name=model_name,
        provider=openai_provider,
    )


class OllamaEmbeddingModel(EmbeddingModel):
    """pydantic-ai embedding model backed by Ollama's native ``/api/embed``.

    Unlike the OpenAI-compatible shim, the native endpoint needs no API key
    and always returns the model's full vector. Dimension negotiation is the
    caller's concern: :meth:`detect_dimensions` probes the real vector length
    once so vector stores (e.g. sqlite-vec) can be created with matching
    dimensions.
    """

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        settings: EmbeddingSettings | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = _ollama_root(base_url)
        self._api_key = api_key
        self._http_client = http_client or httpx.AsyncClient(timeout=_EMBED_TIMEOUT)
        super().__init__(settings=settings)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def system(self) -> str:
        return "ollama"

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _post_embed(self, inputs: str | Sequence[str]) -> dict[str, Any]:
        body = {"model": self._model_name, "input": inputs}
        try:
            response = await self._http_client.post(
                f"{self._base_url}/api/embed",
                json=body,
                headers=self._headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ModelHTTPError(
                status_code=e.response.status_code,
                model_name=self.model_name,
                body=e.response.text,
                headers=dict(e.response.headers),
            ) from e
        except httpx.RequestError as e:
            raise ModelAPIError(model_name=self.model_name, message=str(e)) from e
        return response.json()

    async def embed(
        self,
        inputs: str | Sequence[str],
        *,
        input_type: EmbedInputType,
        settings: EmbeddingSettings | None = None,
    ) -> EmbeddingResult:
        check_allow_model_requests()
        inputs, settings = self.prepare_embed(inputs, settings)
        data = await self._post_embed(inputs)
        return EmbeddingResult(
            embeddings=data["embeddings"],
            inputs=inputs,
            input_type=input_type,
            model_name=data.get("model") or self._model_name,
            provider_name="ollama",
            usage=RequestUsage(input_tokens=data.get("prompt_eval_count", 0)),
        )

    async def detect_dimensions(self) -> int:
        """Probe the model's native embedding length with a one-token input."""
        data = await self._post_embed(["a"])
        embeddings = data.get("embeddings") or []
        if not embeddings:
            raise ModelAPIError(
                model_name=self.model_name,
                message="Ollama response contained no embeddings",
            )
        return len(embeddings[0])


def make_embed_model(
    spec: str,
    dimensions: int | None = None,
) -> EmbeddingModel:
    """Build an embedding model from a 'provider/model' spec.

    Providers with ``api_type = "ollama"`` use the native Ollama API; all
    other providers use the OpenAI-compatible embeddings endpoint.
    """
    provider_name, model_name = _parse_spec(spec)
    cfg = _get_provider(provider_name)
    if cfg.api_type == "ollama":
        return OllamaEmbeddingModel(
            model_name,
            base_url=_ollama_root(cfg.url),
            api_key=cfg.key or None,
            http_client=_get_http_client_for_provider(provider_name),
        )
    kwargs: dict = {}
    if dimensions is not None:
        kwargs["settings"] = EmbeddingSettings(dimensions=dimensions)
    return OpenAIEmbeddingModel(
        model_name,
        provider=_make_openai_provider(provider_name),
        **kwargs,
    )


def make_openai_client_args(spec: str) -> dict:
    """Return kwargs suitable for openai.AsyncOpenAI(**...) from a model spec.

    Useful for services (image gen/edit) that use the raw OpenAI client rather
    than pydantic-ai model objects.

    Returns: {"api_key": ..., "base_url": ..., "model": ...}
    """
    provider_name, model_name = _parse_spec(spec)
    cfg = _get_provider(provider_name)
    return {
        "api_key": cfg.key,
        "base_url": _openai_base_url(cfg),
        "model": model_name,
    }
