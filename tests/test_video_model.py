from types import SimpleNamespace

from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from kmua.plugins.agent.video_model import VideoCapableOpenAIChatModel


def test_process_response_forwards_openai_model_settings(monkeypatch) -> None:
    forwarded: dict[str, bool] = {}

    def process_response(
        self,
        response,
        *,
        include_raw_annotations: bool = False,
        include_unmapped_response_data: bool = False,
    ) -> ModelResponse:
        forwarded["include_raw_annotations"] = include_raw_annotations
        forwarded["include_unmapped_response_data"] = include_unmapped_response_data
        return ModelResponse(parts=[])

    monkeypatch.setattr(OpenAIChatModel, "_process_response", process_response)
    model = VideoCapableOpenAIChatModel(
        model_name="test-model",
        provider=OpenAIProvider(api_key="test"),
    )

    model._process_response(
        SimpleNamespace(usage=None),
        include_raw_annotations=True,
        include_unmapped_response_data=True,
    )

    assert forwarded == {
        "include_raw_annotations": True,
        "include_unmapped_response_data": True,
    }
