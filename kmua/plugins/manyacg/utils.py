import asyncio
import io

import httpx
from PIL import Image

from kmua import common

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
    picture: dict,
) -> str | bytes:
    image_url = picture["original"]

    cache: str | None = await common.memttlcache.get(f"artwork:pic_file_id:{image_url}")
    if cache is not None:
        return cache

    pic_bytes: bytes = await (await client.get(image_url)).aread()

    if (
        len(pic_bytes) > 1024 * 1024 * 10
        or picture["width"] + picture["height"] > 10000
    ):
        pic_bytes = await asyncio.to_thread(_resize_image, pic_bytes)

    return pic_bytes
