import meilisearch
from kmua.config import settings
from kmua.logger import logger

meili_client = None
meili_api = settings.get("meilisearch_api")
meili_key = settings.get("meilisearch_key")
if meili_api and meili_key:
    logger.debug("initing meilisearch client...")
    try:
        meili_client = meilisearch.Client(meili_api, meili_key)
        logger.debug(f"meilisearch client: {meili_client.health()}")
    except Exception as e:
        logger.error(f"meilisearch client error: {e.__class__.__name__}: {e}")
        exit(1)
