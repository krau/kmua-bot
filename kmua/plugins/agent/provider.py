from __future__ import annotations

from typing import Any

from pydantic_ai.embeddings import EmbeddingSettings
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from kmua.config import ProviderConfig, app_config

# Import video-capable model
from .video_model import VideoCapableOpenAIChatModel


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


def _make_openai_provider(provider_name: str) -> OpenAIProvider:
    cfg = _get_provider(provider_name)
    return OpenAIProvider(base_url=cfg.url, api_key=cfg.key)


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


def make_embed_model(
    spec: str,
    dimensions: int | None = None,
) -> OpenAIEmbeddingModel:
    """Build an OpenAIEmbeddingModel from a 'provider/model' spec."""
    provider_name, model_name = _parse_spec(spec)
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
        "base_url": cfg.url,
        "model": model_name,
    }
