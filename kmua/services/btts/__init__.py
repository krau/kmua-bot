import httpx
from pydantic import BaseModel

from kmua.config import app_config


class FormattedSearchHit(BaseModel):
    id: str
    type: str
    user_id: str
    chat_id: str
    timestamp: str
    message: str  # formatted message text, only includes highlighted parts


class SearchHit(BaseModel):
    id: int  # message id
    type: int  # message type id (see below)
    user_id: int  # user id
    chat_id: int  # chat id
    timestamp: int  # message timestamp
    message: str  # message text (all text, not formatted)
    _formatted: FormattedSearchHit | None = None


"""
const (
	MessageTypeText MessageType = iota
	MessageTypePhoto
	MessageTypeVideo
	MessageTypeDocument
	MessageTypeVoice
	MessageTypeAudio
	MessageTypePoll
	MessageTypeStory
)

var MessageTypeFromString = map[string]MessageType{
	"text":     MessageTypeText,
	"photo":    MessageTypePhoto,
	"video":    MessageTypeVideo,
	"document": MessageTypeDocument,
	"voice":    MessageTypeVoice,
	"audio":    MessageTypeAudio,
	"poll":     MessageTypePoll,
	"story":    MessageTypeStory,
}
"""


class SearchResult(BaseModel):
    hits: list[SearchHit]
    # processingTimeMs: int | None
    estimatedTotalHits: int | None = None


class SearchResultResponse(BaseModel):
    results: SearchResult
    status: str


class _BTTSClient:
    def __init__(self, api_key: str | None, api_url: str):
        self.api_key = api_key
        self.base_url = api_url
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "BTTSClient/kmua",
            },
            base_url=self.base_url,
        )

    async def indexed(self) -> tuple[list[int], str]:
        try:
            resp = await self.client.get("indexed")
            resp.raise_for_status()
            data = resp.json()
            chats = data.get("chats", [])
            chat_ids = [int(chat["chat_id"]) for chat in chats]
            return chat_ids, ""
        except httpx.HTTPStatusError as e:
            return [], f"HTTP error: {e.response.status_code} - {e.response.text}"
        except httpx.RequestError as e:
            return [], f"Request error: {str(e)}"
        except Exception as e:
            return [], f"Unexpected error: {str(e)}"

    async def search(
        self,
        query: str,
        chat_id: int,
        offset: int = 0,
        limit: int = 10,
        types: str = "",  # comma-separated types like "text,photo,video"
        users: str = "",
    ) -> tuple[SearchResultResponse | None, str]:
        try:
            queries = {
                "q": query,
                "chat_id": chat_id,
                "offset": offset,
                "limit": limit,
                "types": types,
                "users": users,
            }
            resp = await self.client.get(f"/index/{chat_id}/search", params=queries)
            resp.raise_for_status()
            data = SearchResultResponse.model_validate(resp.json())
            return data, ""
        except httpx.HTTPStatusError as e:
            return None, f"HTTP error: {e.response.status_code} - {e.response.text}"
        except httpx.RequestError as e:
            return None, f"Request error: {str(e)}"
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"


btts_client: _BTTSClient | None = None
if app_config.btts:
    btts_client = _BTTSClient(
        api_key=app_config.btts_api_key,
        api_url=app_config.btts_api_url or "http://localhost:39415",
    )

__all__ = [
    "btts_client",
    "SearchHit",
    "FormattedSearchHit",
    "SearchResult",
    "SearchResultResponse",
]
