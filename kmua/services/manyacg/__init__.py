import re

import httpx

from kmua.config import app_config


class _ManyacgClient:
    def __init__(
        self,
        url: str = app_config.manyacg_api_url,
        api_key: str | None = app_config.manyacg_api_key,
    ):
        self.api_key = api_key
        self.url = url
        headers = {
            "User-Agent": "KMUA ManyacgClient",
        }
        self.client = httpx.AsyncClient(
            base_url=self.url,
            headers=headers,
            timeout=httpx.Timeout(60, connect=10, read=30),
        )

    async def fetch_artwork(
        self, artwork_url: str
    ) -> httpx.Response:  # TODO: type hint
        if not self.api_key:
            raise ValueError("API key is not set")
        params = {"url": artwork_url}
        headers = {"X-API-KEY": self.api_key}
        response = await self.client.get(
            "/artwork/fetch",
            params=params,
            headers=headers,
            follow_redirects=True,
            timeout=60,
        )
        return response

    async def random_artwork(
        self,
        limit: int = 1,
        r18: int = 2,
    ) -> httpx.Response:
        params = {"limit": limit, "r18": r18}
        resp = await self.client.get("/artwork/random", params=params)
        return resp


manyacg_client: _ManyacgClient | None = None
if app_config.manyacg_api_url:
    manyacg_client = _ManyacgClient(
        url=app_config.manyacg_api_url, api_key=app_config.manyacg_api_key
    )

PIXIV_REGEX = re.compile(
    r"pixiv\.net/(?:artworks/|i/|member_illust\.php\?(?:[\w=&]*\&|)illust_id=)(\d+)"
)
TWITTER_REGEX = re.compile(r"(?:twitter|x)\.com/([^/]+)/status/(\d+)")
BILIBILI_REGEX = re.compile(r"t\.bilibili\.com/(\d+)|bilibili\.com/opus/(\d+)")
DANBOORU_REGEX = re.compile(r"danbooru\.donmai\.us/posts/\d+")
KEMONO_REGEX = re.compile(r"kemono\.su/\w+/user/\d+/post/\d+")
YANDERE_REGEX = re.compile(r"yande\.re/post/show/\d+")
NHENTAI_REGEX = re.compile(r"nhentai\.net/g/\d+")
ARTWORK_ALL_REGEX = [
    PIXIV_REGEX,
    TWITTER_REGEX,
    BILIBILI_REGEX,
    DANBOORU_REGEX,
    KEMONO_REGEX,
    YANDERE_REGEX,
    NHENTAI_REGEX,
]


__all__ = ["manyacg_client", "ARTWORK_ALL_REGEX"]
