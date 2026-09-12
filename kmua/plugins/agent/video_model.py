"""Video-capable OpenAI Chat Model for pydantic-ai.

Sends video BinaryContent as a video_url parameter to the OpenAI API.

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
    return media_type.startswith("video/")


class VideoCapableOpenAIChatModel(OpenAIChatModel):
    """OpenAI Chat Model that supports video content via data URIs.

    Maps video BinaryContent to video_url with a base64 data URI, which
    modern vision models accept for video input.
    """

    @property
    def _streamed_response_cls(self) -> type[OpenAIStreamedResponse]:
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

        Video is sent as a base64 data URI under the video_url parameter.
        """
        if _is_video_media_type(item.media_type):  # type: ignore
            data_uri = (
                f"data:{item.media_type};base64,{base64.b64encode(item.data).decode()}"  # type: ignore
            )

            return {
                "type": "video_url",
                "video_url": {
                    "url": data_uri,
                },
            }

        return await super()._map_binary_content_item(item)


def make_video_capable_chat_model(spec: str) -> VideoCapableOpenAIChatModel:
    """Build a VideoCapableOpenAIChatModel from a 'provider/model' spec."""
    from .provider import _make_openai_provider, _parse_spec

    provider_name, model_name = _parse_spec(spec)
    return VideoCapableOpenAIChatModel(
        model_name=model_name,
        provider=_make_openai_provider(provider_name),
    )
