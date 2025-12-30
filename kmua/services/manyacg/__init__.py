import re

import httpx
from pydantic import BaseModel

from kmua.config import app_config


class FetchedArtist(BaseModel):
    name: str
    username: str | None
    uid: str | None


class FetchedPicture(BaseModel):
    index: int
    width: int
    height: int
    thumbnail: str
    original: str
    file_name: str | None


class UgoiraFrame(BaseModel):
    file: str
    delay: int


class UgoiraMetaData(BaseModel):
    poster_original: str | None
    poster_thumb: str | None
    original_zip: str
    thumb_zip: str | None
    mime_type: str
    frames: list[UgoiraFrame]
    width: int
    height: int


class FetchedUgoira(BaseModel):
    index: int
    data: UgoiraMetaData


class FetchedVideo(BaseModel):
    url: str
    poster: str | None
    mime_type: str | None
    index: int
    width: int | None
    height: int | None
    duration: int | None  # in milliseconds


class FetchedArtwork(BaseModel):
    cache_id: str | None = None
    title: str
    description: str
    tags: list[str]
    source_url: str
    artist: FetchedArtist | None
    source_type: str
    r18: bool
    pictures: list[FetchedPicture] | None = None
    ugoira_metas: list[FetchedUgoira] | None = None
    videos: list[FetchedVideo] | None = None


class FetchArtworkResponse(BaseModel):
    status: int
    message: str
    data: FetchedArtwork | None


class Artist(BaseModel):
    id: str
    name: str
    username: str | None
    uid: str | None
    type: str | None


class Picture(BaseModel):
    id: str
    width: int
    height: int
    index: int
    hash: str
    thumb_hash: str
    file_name: str | None
    thumbnail: str
    regular: str


class Artwork(BaseModel):
    id: str
    created_at: str
    title: str
    description: str
    tags: list[str]
    source_url: str
    source_type: str
    r18: bool
    artist: Artist
    pictures: list[Picture]


class RandomArtworkResponse(BaseModel):
    status: int
    message: str
    data: list[Artwork] | None


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

    async def fetch_artwork(self, artwork_url: str) -> FetchArtworkResponse:
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
        resp_model = FetchArtworkResponse.model_validate(response.json())
        return resp_model

    async def random_artwork(
        self,
        limit: int = 1,
        r18: int = 2,
    ) -> RandomArtworkResponse:
        params = {"limit": limit, "r18": r18}
        resp = await self.client.get("/artwork/random", params=params)
        resp_model = RandomArtworkResponse.model_validate(resp.json())
        return resp_model


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
KEMONO_REGEX = re.compile(r"kemono\.cr/\w+/user/\d+/post/\d+")
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
