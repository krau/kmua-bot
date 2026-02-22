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


async def _url_to_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


class _ImageGenerationClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

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
                image_bytes = base64.b64decode(item.b64_json)
            elif item.url:
                image_bytes = await _url_to_bytes(item.url)
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
    def __init__(self, api_key: str, base_url: str, model: str):
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def edit(
        self,
        prompt: str,
        image_data: bytes,
        image_filename: str = "image.png",
        image_mime_type: str = "image/png",
        mask_data: bytes | None = None,
        size: str = "1024x1024",
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
                result_bytes = base64.b64decode(item.b64_json)
            elif item.url:
                result_bytes = await _url_to_bytes(item.url)
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


image_gen_client: _ImageGenerationClient | None = None
image_edit_client: _ImageEditClient | None = None

if (
    app_config.agent_image_gen_model
    and app_config.agent_image_gen_provider_url
    and app_config.agent_image_gen_api_key
):
    image_gen_client = _ImageGenerationClient(
        api_key=app_config.agent_image_gen_api_key,
        base_url=app_config.agent_image_gen_provider_url,
        model=app_config.agent_image_gen_model,
    )

_edit_model = app_config.agent_image_edit_model or app_config.agent_image_gen_model
_edit_url = (
    app_config.agent_image_edit_provider_url or app_config.agent_image_gen_provider_url
)
_edit_key = app_config.agent_image_edit_api_key or app_config.agent_image_gen_api_key

if _edit_model and _edit_url and _edit_key:
    image_edit_client = _ImageEditClient(
        api_key=_edit_key,
        base_url=_edit_url,
        model=_edit_model,
    )

__all__ = [
    "image_gen_client",
    "image_edit_client",
    "ImageGenResult",
    "ImageEditResult",
]
