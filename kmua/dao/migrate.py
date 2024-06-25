from kmua.dao._db import _db, commit
from kmua.models.models import ChatData, Quote
from kmua.logger import logger
from .chat_service import delete_chat_data_and_quotes


def fix_none_chat_id_quotes() -> tuple[int, int, int]:
    quotes = _db.query(Quote).filter(Quote.chat_id.is_(None)).all()
    logger.debug(f"找到 {len(quotes)} 条没有 chat_id 的 quote")
    invalid_chat_ids = []
    failed_count = 0
    for quote in quotes:
        try:
            chat_id = int("-100" + quote.link.split("/")[-2])
        except ValueError:
            logger.warning(f"无法解析链接: {quote.link}")
            failed_count += 1
            _db.delete(quote)
            commit()
            continue
        if chat_id in invalid_chat_ids:
            failed_count += 1
            continue
        db_chat = _db.query(ChatData).filter(ChatData.id == chat_id).first()
        if not db_chat:
            failed_count += 1
            invalid_chat_ids.append(chat_id)
            logger.warning(f"无法找到对应的 chat: {chat_id}")
            continue
        quote.chat_id = db_chat.id
        commit()
    return len(quotes), len(invalid_chat_ids), failed_count


def delete_no_supergroup_chats() -> int:
    chats = _db.query(ChatData).filter(ChatData.id > -1000000000000).all()
    logger.debug(f"找到 {len(chats)} 个非超级群组")
    for chat in chats:
        delete_chat_data_and_quotes(chat.id)
    return len(chats)
