"""Video-capable OpenAI Chat Model for pydantic-ai.

This module provides a custom OpenAIChatModel subclass that supports video content
by sending video BinaryContent as video_url parameter to the OpenAI API.

Prompt-cache hit statistics are recorded for every model request via
:mod:`kmua.plugins.agent.cache_stats`.
"""

import base64
from typing import Any

from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIStreamedResponse

from kmua.plugins.agent.cache_stats import (
    CacheStatsOpenAIStreamedResponse,
    log_cache_stats,
)


def _is_video_media_type(media_type: str) -> bool:
    """Check if media type is a video format."""
    return media_type.startswith("video/")


class VideoCapableOpenAIChatModel(OpenAIChatModel):
    """OpenAI Chat Model that supports video content via data URIs.

    This model extends OpenAIChatModel to handle video BinaryContent by mapping
    it to video_url format with base64 data URI, which is supported by
    modern vision models for video input.
    """

    @property
    def _streamed_response_cls(self) -> type[OpenAIStreamedResponse]:
        """Return the StreamedResponse type used for streamed responses."""
        return CacheStatsOpenAIStreamedResponse

    def _process_response(self, response: Any) -> ModelResponse:
        model_response = super()._process_response(response)
        log_cache_stats(
            self.model_name,
            getattr(response, "usage", None),
            model_response.usage,
        )
        return model_response

    async def _map_binary_content_item(self, item: BinaryContent) -> Any:
        """Map a BinaryContent item to a chat completion content part.

        Extends the parent implementation to support video content.
        Video is sent as base64 data URI using video_url parameter.
        """
        # Check if this is a video
        if _is_video_media_type(item.media_type):  # type: ignore
            # For video, we send it as a video_url with data URI
            # The format is: data:video/mp4;base64,...
            # This is supported by modern OpenAI-compatible APIs for video input
            data_uri = (
                f"data:{item.media_type};base64,{base64.b64encode(item.data).decode()}"  # type: ignore
            )

            # Return video_url format instead of image_url
            # This is a dict that matches the OpenAI API video_url content part format
            return {
                "type": "video_url",
                "video_url": {
                    "url": data_uri,
                },
            }

        # For non-video content, use parent implementation
        return await super()._map_binary_content_item(item)


def make_video_capable_chat_model(spec: str) -> VideoCapableOpenAIChatModel:
    """Build a VideoCapableOpenAIChatModel from a 'provider/model' spec."""
    from .provider import _make_openai_provider, _parse_spec

    provider_name, model_name = _parse_spec(spec)
    return VideoCapableOpenAIChatModel(
        model_name=model_name,
        provider=_make_openai_provider(provider_name),
    )
