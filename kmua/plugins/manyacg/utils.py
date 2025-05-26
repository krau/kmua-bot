import io

import httpx
from PIL import Image


async def prepare_media(
    client: httpx.AsyncClient,
    picture: dict,
) -> str | bytes:
    image_url = picture["original"]

    # cache: bytes | None = (
    #     redis_client.get(f"kmua_file_id_{image_url}") if redis_client else None
    # )
    # if cache is not None:
    #     return cache.decode("utf-8")

    pic_bytes: bytes = (await client.get(image_url)).content

    # resize image if size > 10M or exceeds width/height limitation
    if (
        len(pic_bytes) > 1024 * 1024 * 10
        or picture["width"] + picture["height"] > 10000
    ):
        image = Image.open(io.BytesIO(pic_bytes))
        max_size = 2560
        ratio = max_size / max(image.width, image.height)
        if ratio < 1:
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=90)
        pic_bytes = output.getvalue()
        output.close()
    return pic_bytes
