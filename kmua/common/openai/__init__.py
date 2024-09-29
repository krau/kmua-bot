from kmua.config import settings
from kmua.logger import logger

openai_client = None
openai_api = settings.get("openai_api", "").removesuffix("/")
openai_key = settings.get("openai_key")
openai_model = settings.get("openai_model", "gpt-4o-mini")
openai_system = settings.get("openai_system", "你是一只叫kmua的可爱猫娘")

if all((openai_api, openai_key, openai_model)):
    logger.debug("initing openai client...")
    import openai

    try:
        openai_client = openai.OpenAI(
            base_url=openai_api,
            api_key=openai_key,
        )
        logger.debug(f"openai client: {openai_client}")
    except Exception as e:
        logger.error(f"openai client error: {e.__class__.__name__}: {e}")
        exit(1)
