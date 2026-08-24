import asyncio
import io
from typing import BinaryIO

import aiofiles
import httpx
from PIL import Image

from kmua import common
from kmua.common.download import download_capped
from kmua.services.manyacg import FetchedPicture, FetchedVideo

_max_size = 2560
_MAX_PICTURE_BYTES = 100 * 1024 * 1024
_MAX_VIDEO_BYTES = 1024 * 1024 * 1024


async def _stream_video_capped(
    client: httpx.AsyncClient, url: str, save_path: str
) -> None:
    """Stream a video to disk, aborting past the byte cap (the declared
    Content-Length can be missing or wrong). Removes the partial file."""
    written = 0
    try:
        async with aiofiles.open(save_path, "wb") as f:
            async with client.stream("GET", url, timeout=120) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    written += len(chunk)
                    if written > _MAX_VIDEO_BYTES:
                        raise ValueError("Video file too large")
                    await f.write(chunk)
    except BaseException:
        import pathlib

        pathlib.Path(save_path).unlink(missing_ok=True)
        raise
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
        media_bytes: bytes = await download_capped(
            client, media.original, _MAX_PICTURE_BYTES, timeout=60
        )
        if len(media_bytes) >= 1024 * 1024 * 10 or media.width + media.height >= 10000:
            media_bytes = await asyncio.to_thread(_resize_image, media_bytes)
        return io.BytesIO(media_bytes)
    if isinstance(media, FetchedVideo):
        if save_path is not None:
            await _stream_video_capped(client, media.url, save_path)
            return save_path
        video_bytes: bytes = await download_capped(
            client, media.url, _MAX_VIDEO_BYTES, timeout=120
        )
        return io.BytesIO(video_bytes)
