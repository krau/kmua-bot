import asyncio
import io
from typing import BinaryIO

import aiofiles
import httpx
from PIL import Image

from kmua import common
from kmua.services.manyacg import FetchedPicture, FetchedVideo

_max_size = 2560


def _resize_image(pic_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(pic_bytes)) as image:
        ratio = _max_size / max(image.width, image.height)

        if ratio < 1:
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=90)
        processed_bytes = output.getvalue()
        output.close()
        return processed_bytes


async def prepare_media(
    client: httpx.AsyncClient,
    media: FetchedPicture | FetchedVideo,
    save_path: str | None = None,
) -> str | BinaryIO:
    media_url = ""
    if isinstance(media, (FetchedPicture)):
        media_url = media.original
    elif isinstance(media, FetchedVideo):
        media_url = media.url
    if media_url == "":
        raise ValueError("Unsupported media type")
    cache: str | None = await common.memttlcache.get(
        f"artwork:media_file_id:{media_url}"
    )
    if cache is not None:
        return cache
    if isinstance(media, FetchedPicture):
        media_bytes: bytes = await (await client.get(media.original)).aread()
        if len(media_bytes) >= 1024 * 1024 * 10 or media.width + media.height >= 10000:
            media_bytes = await asyncio.to_thread(_resize_image, media_bytes)
        return io.BytesIO(media_bytes)
    if isinstance(media, FetchedVideo):
        # head request to get content length
        head_resp = await client.head(media.url)
        content_length = head_resp.headers.get("Content-Length")
        if (
            content_length is not None and int(content_length) > 1024 * 1024 * 1024
        ):  # 1GB
            raise ValueError("Video file too large")
        if save_path is not None:
            async with aiofiles.open(save_path, "wb") as f:
                async with client.stream("GET", media.url) as resp:
                    async for chunk in resp.aiter_bytes():
                        await f.write(chunk)
            return save_path
        else:
            video_bytes: bytes = await (await client.get(media.url)).aread()
            return io.BytesIO(video_bytes)
