import asyncio
import base64
from dataclasses import dataclass
from io import BytesIO

import httpx
from openai import AsyncOpenAI

from kmua.config import app_config
from kmua.logger import logger


@dataclass
class ImageGenResult:
    success: bool
    data: bytes | None = None
    revised_prompt: str | None = None
    error: str | None = None


@dataclass
class ImageEditResult:
    success: bool
    data: bytes | None = None
    revised_prompt: str | None = None
    error: str | None = None


async def _url_to_bytes(url: str, proxy: str | None = None) -> bytes:
    # Image result URLs (when b64_json is absent) are fetched via httpx.
    # Reuse the agent proxy when the URL belongs to the provider's domain;
    # otherwise direct fetch is fine. Minimal closed loop: honour explicit
    # image-model provider proxy, fallback to global agent_proxy.
    http_client: httpx.AsyncClient | None = None
    if proxy is None:
        try:
            from kmua.common.http import get_agent_http_client

            http_client = get_agent_http_client(None)
        except Exception:
            http_client = None
    else:
        try:
            from kmua.common.http import get_agent_http_client

            http_client = get_agent_http_client(proxy)
        except Exception:
            http_client = None
    if http_client is not None:
        resp = await http_client.get(url)
        resp.raise_for_status()
        return resp.content
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _proxy_for_spec(spec: str) -> str | None:
    """Resolve proxy for an image model spec (provider proxy > global)."""
    provider_name, _ = _parse_model_spec(spec)
    providers = app_config.agent_providers
    cfg = providers.get(provider_name)
    if cfg is not None and cfg.proxy:
        return cfg.proxy
    return app_config.agent_proxy


class _ImageGenerationClient:
    def __init__(
        self, api_key: str, base_url: str, model: str, proxy: str | None = None
    ):
        self.model = model
        http_client: httpx.AsyncClient | None = None
        if proxy is not None:
            try:
                from kmua.common.http import get_agent_http_client

                http_client = get_agent_http_client(proxy)
            except Exception:
                http_client = None
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        self._proxy = proxy

    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> ImageGenResult:
        try:
            response = await self._client.images.generate(
                model=self.model,
                prompt=prompt,
                size=size,  # type: ignore[arg-type]
                quality=quality,  # type: ignore[arg-type]
                n=n,
                response_format="b64_json",
            )
            item = response.data[0]  # type: ignore[index]
            if item.b64_json:
                image_bytes = await asyncio.to_thread(base64.b64decode, item.b64_json)
            elif item.url:
                image_bytes = await _url_to_bytes(item.url, self._proxy)
            else:
                return ImageGenResult(
                    success=False, error="No image data returned by the model."
                )
            return ImageGenResult(
                success=True,
                data=image_bytes,
                revised_prompt=item.revised_prompt,
            )
        except Exception as e:
            logger.error(f"ImageGen error: {e.__class__.__name__}: {e}")
            return ImageGenResult(success=False, error=f"{e.__class__.__name__}: {e}")


class _ImageEditClient:
    def __init__(
        self, api_key: str, base_url: str, model: str, proxy: str | None = None
    ):
        self.model = model
        http_client: httpx.AsyncClient | None = None
        if proxy is not None:
            try:
                from kmua.common.http import get_agent_http_client

                http_client = get_agent_http_client(proxy)
            except Exception:
                http_client = None
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        self._proxy = proxy

    async def edit(
        self,
        prompt: str,
        image_data: bytes,
        image_filename: str = "image.png",
        image_mime_type: str = "image/png",
        mask_data: bytes | None = None,
        size: str = "auto",
        n: int = 1,
    ) -> ImageEditResult:
        try:
            image_file = (image_filename, BytesIO(image_data), image_mime_type)
            kwargs: dict = dict(
                model=self.model,
                image=image_file,
                prompt=prompt,
                size=size,  # type: ignore[arg-type]
                n=n,
                response_format="b64_json",
            )
            if mask_data is not None:
                kwargs["mask"] = ("mask.png", BytesIO(mask_data), "image/png")
            response = await self._client.images.edit(**kwargs)
            item = response.data[0]
            if item.b64_json:
                result_bytes = await asyncio.to_thread(base64.b64decode, item.b64_json)
            elif item.url:
                result_bytes = await _url_to_bytes(item.url, self._proxy)
            else:
                return ImageEditResult(
                    success=False, error="No image data returned by the model."
                )
            return ImageEditResult(
                success=True,
                data=result_bytes,
                revised_prompt=item.revised_prompt,
            )
        except Exception as e:
            logger.error(f"ImageEdit error: {e.__class__.__name__}: {e}")
            return ImageEditResult(success=False, error=f"{e.__class__.__name__}: {e}")


def _parse_model_spec(spec: str) -> tuple[str, str]:
    if "/" in spec:
        provider_name, _, model_name = spec.partition("/")
        return provider_name.strip(), model_name.strip()
    return "default", spec.strip()


def _make_openai_client_args(spec: str) -> dict[str, str]:
    provider_name, model_name = _parse_model_spec(spec)
    providers = app_config.agent_providers
    if provider_name not in providers:
        raise ValueError(
            f"Provider {provider_name!r} not found in agent_providers. "
            f"Available: {list(providers.keys())}"
        )
    provider_cfg = providers[provider_name]
    return {
        "api_key": provider_cfg.key,
        "base_url": provider_cfg.url,
        "model": model_name,
    }


image_gen_client: _ImageGenerationClient | None = None
image_edit_client: _ImageEditClient | None = None

if app_config.agent and app_config.agent_image_gen_model:
    _gen_args = _make_openai_client_args(app_config.agent_image_gen_model)
    image_gen_client = _ImageGenerationClient(
        api_key=_gen_args["api_key"],
        base_url=_gen_args["base_url"],
        model=_gen_args["model"],
        proxy=_proxy_for_spec(app_config.agent_image_gen_model),
    )

    # Edit client: use agent_image_edit_model if set, else fall back to gen model
    _edit_spec = app_config.agent_image_edit_model or app_config.agent_image_gen_model
    _edit_args = _make_openai_client_args(_edit_spec)
    image_edit_client = _ImageEditClient(
        api_key=_edit_args["api_key"],
        base_url=_edit_args["base_url"],
        model=_edit_args["model"],
        proxy=_proxy_for_spec(_edit_spec),
    )
__all__ = [
    "image_gen_client",
    "image_edit_client",
    "ImageGenResult",
    "ImageEditResult",
]
