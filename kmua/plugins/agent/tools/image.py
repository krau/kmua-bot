from dataclasses import dataclass
from io import BytesIO

import pyrogram
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import BinaryContent, ModelRequest, UserPromptPart

from kmua.common import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import image_gen

from .. import datatype, state


@dataclass
class ImageOperationResult:
    success: bool
    message: str | None = None
    revised_prompt: str | None = None


async def _find_image_in_history(
    ctx: RunContext[datatype.ContextDeps],
) -> tuple[bytes, str] | None:
    for cache_key in (
        state.last_user_image_key(ctx.deps.chat_id, ctx.deps.user_id),
        state.last_edited_image_key(ctx.deps.chat_id, ctx.deps.user_id),
    ):
        file_id: str | None = await memttlcache.get(cache_key)
        if file_id is None:
            continue
        try:
            file_obj = await ctx.deps.client.download_media(
                message=file_id, in_memory=True
            )
            if isinstance(file_obj, BytesIO):
                logger.debug(f"edit_image: found image via cache key={cache_key!r}")
                return file_obj.getvalue(), "image/jpeg"
        except Exception as e:
            logger.warning(
                f"edit_image: failed to download cached file_id from {cache_key!r}: {e}"
            )

    for msg in reversed(ctx.deps.history):
        if not isinstance(msg, ModelRequest):
            continue
        for part in reversed(list(msg.parts)):
            if not isinstance(part, UserPromptPart):
                continue
            content = part.content
            if isinstance(content, str):
                continue
            for item in reversed(list(content)):
                if isinstance(item, BinaryContent) and item.media_type.startswith(  # type: ignore[union-attr]
                    "image/"
                ):
                    return item.data, item.media_type  # type: ignore[union-attr]
    return None


async def generate_image(
    ctx: RunContext[datatype.ContextDeps],
    prompt: str,
    size: str = "1024x1024",
) -> ImageOperationResult:
    """Generate an image from a text description and send it to the chat.

    Use this tool when the user asks you to draw, generate, create or produce an image
    based on a text description. Do NOT use this when the user sends an image and asks
    you to modify it — use edit_image instead.

    Args:
        prompt: Detailed description of the image to generate. Be as specific and
            descriptive as possible about subject, style, colors, composition, etc.
        size: Image dimensions. Supported values depend on the model; common options
            are "1024x1024", "1792x1024", "1024x1792". Defaults to "1024x1024".

    Returns:
        An ImageOperationResult indicating success or failure.
    """
    if not image_gen.image_gen_client:
        return ImageOperationResult(
            success=False, message="Image generation service is not configured."
        )
    gen_client = image_gen.image_gen_client

    if not prompt or not prompt.strip():
        raise ModelRetry("A non-empty prompt is required to generate an image.")
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return ImageOperationResult(
            success=False, message="Current message context is unavailable."
        )
    logger.debug(
        f"generate_image called: chat_id={ctx.deps.chat_id}, user_id={ctx.deps.user_id}, prompt={prompt[:100]}"
    )
    await ctx.deps.client.send_chat_action(
        chat_id=ctx.deps.chat_id,
        action=pyrogram.enums.chat_action.ChatAction.UPLOAD_PHOTO,
    )
    result = await gen_client.generate(prompt=prompt, size=size)
    if not result.success or not result.data:
        return ImageOperationResult(
            success=False,
            message=f"Image generation failed: {result.error}",
        )
    try:
        await ctx.deps.client.send_photo(
            chat_id=ctx.deps.chat_id,
            photo=BytesIO(result.data),
            reply_parameters=pyrogram.types.ReplyParameters(
                message_id=ctx.deps.message.id,
            ),
        )
    except Exception as e:
        logger.error(f"Failed to send generated image: {e.__class__.__name__}: {e}")
        return ImageOperationResult(
            success=False,
            message=f"Image was generated but could not be sent: {e.__class__.__name__}",
        )
    return ImageOperationResult(
        success=True,
        revised_prompt=result.revised_prompt,
    )


async def edit_image(
    ctx: RunContext[datatype.ContextDeps],
    prompt: str,
    size: str = "1024x1024",
) -> ImageOperationResult:
    """Edit or modify an image provided by the user and send the result to the chat.

    Use this tool when the user has sent an image and asks you to modify, edit,
    transform or alter it in some way based on their description.

    Args:
        prompt: Detailed description of what changes to make to the image.
        size: Output image dimensions. Defaults to "1024x1024".

    Returns:
        An ImageOperationResult indicating success or failure.
    """
    if not image_gen.image_edit_client:
        return ImageOperationResult(
            success=False, message="Image editing service is not configured."
        )
    edit_client = image_gen.image_edit_client
    if not prompt or not prompt.strip():
        raise ModelRetry("A non-empty prompt is required to edit an image.")
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return ImageOperationResult(
            success=False, message="Current message context is unavailable."
        )

    logger.debug(
        f"edit_image called: chat_id={ctx.deps.chat_id}, user_id={ctx.deps.user_id}, prompt={prompt[:100]}"
    )

    image_bytes: bytes | None = None
    mime_type: str = "image/jpeg"

    source_message: pyrogram.types.Message | None = None
    if ctx.deps.message.photo:
        source_message = ctx.deps.message
    elif ctx.deps.message.reply_to_message and ctx.deps.message.reply_to_message.photo:
        source_message = ctx.deps.message.reply_to_message
    elif (
        ctx.deps.message.document
        and ctx.deps.message.document.mime_type
        and ctx.deps.message.document.mime_type.startswith("image/")
    ):
        source_message = ctx.deps.message
    elif (
        ctx.deps.message.reply_to_message
        and ctx.deps.message.reply_to_message.document
        and ctx.deps.message.reply_to_message.document.mime_type
        and ctx.deps.message.reply_to_message.document.mime_type.startswith("image/")
    ):
        source_message = ctx.deps.message.reply_to_message

    if source_message is not None:
        try:
            if source_message.photo:
                file_id = source_message.photo.file_id
                mime_type = "image/jpeg"
            else:
                doc = source_message.document
                assert doc is not None
                file_id = doc.file_id
                mime_type = doc.mime_type or "image/png"

            file_obj = await ctx.deps.client.download_media(
                message=file_id, in_memory=True
            )
            if not isinstance(file_obj, BytesIO):
                return ImageOperationResult(
                    success=False, message="Failed to download source image."
                )
            image_bytes = file_obj.getvalue()
        except Exception as e:
            logger.error(
                f"Failed to download source image: {e.__class__.__name__}: {e}"
            )
            return ImageOperationResult(
                success=False,
                message=f"Failed to download source image: {e.__class__.__name__}",
            )
    else:
        history_image = await _find_image_in_history(ctx)
        if history_image is None:
            return ImageOperationResult(
                success=False,
                message=(
                    "No image found in the current message, the message being "
                    "replied to, or the recent conversation history. "
                    "Please send an image to edit."
                ),
            )
        image_bytes, mime_type = history_image

    assert image_bytes is not None
    await ctx.deps.client.send_chat_action(
        chat_id=ctx.deps.chat_id,
        action=pyrogram.enums.chat_action.ChatAction.UPLOAD_PHOTO,
    )
    result = await edit_client.edit(
        prompt=prompt,
        image_data=image_bytes,
        image_filename="image.jpg" if mime_type == "image/jpeg" else "image.png",
        image_mime_type=mime_type,
        size=size,
    )
    if not result.success or not result.data:
        return ImageOperationResult(
            success=False,
            message=f"Image editing failed: {result.error}",
        )
    try:
        sent = await ctx.deps.client.send_photo(
            chat_id=ctx.deps.chat_id,
            photo=BytesIO(result.data),
            reply_parameters=pyrogram.types.ReplyParameters(
                message_id=ctx.deps.message.id,
            ),
        )
    except Exception as e:
        logger.error(f"Failed to send edited image: {e.__class__.__name__}: {e}")
        return ImageOperationResult(
            success=False,
            message=f"Image was edited but could not be sent: {e.__class__.__name__}",
        )
    if sent and sent.photo:
        await memttlcache.set(
            state.last_edited_image_key(ctx.deps.chat_id, ctx.deps.user_id),
            sent.photo.file_id,
            ttl=app_config.cachettl_agent_history,
        )
    return ImageOperationResult(
        success=True,
        revised_prompt=result.revised_prompt,
    )
