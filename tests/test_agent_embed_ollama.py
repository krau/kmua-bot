"""Ollama-native embedding support for the sticker-memory embedder."""

from __future__ import annotations

import json

import httpx
import pytest

from kmua.config import ProviderConfig, app_config
from kmua.plugins.agent import provider, sticker_memory, sticker_vec


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_make_embed_model_dispatches_ollama(monkeypatch):
    monkeypatch.setattr(
        app_config,
        "agent_providers",
        {
            "local": ProviderConfig(
                url="http://localhost:11434/v1", key="ollama", api_type="ollama"
            )
        },
    )
    model = provider.make_embed_model("local/nomic-embed-text")
    assert isinstance(model, provider.OllamaEmbeddingModel)
    # 即使配置写了 /v1, 原生 API 根地址也归一化
    assert model.base_url == "http://localhost:11434"
    await model._http_client.aclose()


async def test_embed_uses_native_endpoint_without_dimensions():
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "model": "nomic-embed-text",
                "embeddings": [[0.1, 0.2, 0.3]],
                "prompt_eval_count": 2,
            },
        )

    client = _client_for(handler)
    model = provider.OllamaEmbeddingModel(
        "nomic-embed-text",
        base_url="http://localhost:11434",
        api_key="ollama",
        http_client=client,
    )
    result = await model.embed(["hi"], input_type="query")
    assert result.embeddings == [[0.1, 0.2, 0.3]]
    assert result.model_name == "nomic-embed-text"
    assert result.provider_name == "ollama"
    assert result.usage.input_tokens == 2
    assert seen["path"] == "/api/embed"
    assert seen["body"] == {"model": "nomic-embed-text", "input": ["hi"]}
    assert seen["auth"] == "Bearer ollama"
    await client.aclose()


async def test_embed_does_not_send_key_when_unset():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"model": "m", "embeddings": [[0.1]], "prompt_eval_count": 1},
        )

    client = _client_for(handler)
    model = provider.OllamaEmbeddingModel(
        "m", base_url="http://localhost:11434", http_client=client
    )
    await model.embed(["x"], input_type="document")
    assert seen["auth"] is None
    await client.aclose()


async def test_detect_dimensions_returns_native_length():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("input") == ["a"]
        return httpx.Response(
            200,
            json={"model": "m", "embeddings": [[0.0] * 5], "prompt_eval_count": 1},
        )

    client = _client_for(handler)
    model = provider.OllamaEmbeddingModel(
        "m", base_url="http://localhost:11434", http_client=client
    )
    assert await model.detect_dimensions() == 5
    await client.aclose()


async def test_http_errors_mapped_to_model_http_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _client_for(handler)
    model = provider.OllamaEmbeddingModel(
        "m", base_url="http://localhost:11434", http_client=client
    )
    with pytest.raises(provider.ModelHTTPError) as exc:
        await model.embed(["x"], input_type="query")
    assert exc.value.status_code == 500
    await client.aclose()


async def test_ensure_embed_dimensions_probes_ollama_once(monkeypatch):
    hits = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(
            200,
            json={"model": "m", "embeddings": [[0.0] * 4], "prompt_eval_count": 1},
        )

    client = _client_for(handler)
    model = provider.OllamaEmbeddingModel(
        "m", base_url="http://localhost:11434", http_client=client
    )
    monkeypatch.setattr(sticker_memory, "_embed_model", model)
    monkeypatch.setattr(sticker_memory, "_embed_dimensions", None)
    monkeypatch.setattr(sticker_memory, "_embed_dimensions_resolved", False)

    assert await sticker_memory.ensure_embed_dimensions() == 4
    assert await sticker_memory.ensure_embed_dimensions() == 4
    assert hits["n"] == 1
    await client.aclose()


async def test_ensure_embed_dimensions_falls_back_to_config(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _client_for(handler)
    model = provider.OllamaEmbeddingModel(
        "m", base_url="http://localhost:11434", http_client=client
    )
    monkeypatch.setattr(sticker_memory, "_embed_model", model)
    monkeypatch.setattr(sticker_memory, "_embed_dimensions", None)
    monkeypatch.setattr(sticker_memory, "_embed_dimensions_resolved", False)
    monkeypatch.setattr(app_config, "agent_sticker_embed_dimensions", 512)

    assert await sticker_memory.ensure_embed_dimensions() == 512
    await client.aclose()


async def test_non_ollama_embedder_uses_configured_dimensions(monkeypatch):
    monkeypatch.setattr(sticker_memory, "_embed_model", None)
    monkeypatch.setattr(sticker_memory, "_embed_dimensions", None)
    monkeypatch.setattr(sticker_memory, "_embed_dimensions_resolved", False)
    monkeypatch.setattr(app_config, "agent_sticker_embed_dimensions", 1024)
    assert await sticker_memory.ensure_embed_dimensions() == 1024


async def test_openai_client_args_normalizes_ollama_url(monkeypatch):
    monkeypatch.setattr(
        app_config,
        "agent_providers",
        {
            "local": ProviderConfig(
                url="http://localhost:11434", key="ollama", api_type="ollama"
            )
        },
    )
    args = provider.make_openai_client_args("local/llama3.2")
    assert args["base_url"] == "http://localhost:11434/v1"
    assert args["model"] == "llama3.2"


async def test_sticker_vec_init_uses_probed_dims(monkeypatch, tmp_path):
    db_path = tmp_path / "stickers.db"
    monkeypatch.setattr(app_config, "agent_sticker_db_path", str(db_path))
    monkeypatch.setattr(sticker_vec, "_DB_PATH", None)
    monkeypatch.setattr(sticker_vec, "_INITIALIZED", False)

    await sticker_vec.init(dims=4)
    await sticker_vec.upsert("uid1", "file1", -100123, "一个猫猫贴纸", [0.1] * 4)
    assert await sticker_vec.exists("uid1", -100123)
