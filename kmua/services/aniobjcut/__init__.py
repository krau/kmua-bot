import httpx

from kmua.config import app_config


class _AniObjCutClient:
    def __init__(self, url: str, api_key: str | None = None):
        self.url = url
        self.api_key = api_key
        headers = {
            "User-Agent": "KMUA AniObjCut Client",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.client = httpx.AsyncClient(
            base_url=self.url,
            headers=headers,
            timeout=httpx.Timeout(60, connect=10, read=30),
        )

    async def cut_avatar(
        self,
        file: bytes,
        size: int = 512,
        padding: float = 0.3,
    ) -> bytes:
        try:
            response = await self.client.post(
                "/cut/avatar",
                files={"file": ("avatar.png", file, "image/png")},
                data={"size": size, "padding": padding},
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"HTTP error: {e.response.status_code} - {e.response.text}"
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"Request error: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error: {str(e)}")


aniobjcut_client: _AniObjCutClient | None = None
if app_config.aniobjcut:
    aniobjcut_client = _AniObjCutClient(
        url=app_config.aniobjcut_api_url,
        api_key=app_config.aniobjcut_api_key,
    )

___all__ = [
    "aniobjcut_client",
]
