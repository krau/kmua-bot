from telegram import Chat, Message, User
from sqlalchemy import func, or_
from kmua.dao._db import commit, _db
from kmua.models.models import ChatData, Quote, UserData


def get_quote_by_link(link: str) -> Quote | None:
    return _db.query(Quote).filter(Quote.link == link).first()


def delete_quote(quote: Quote):
    _db.delete(quote)
    commit()


def delete_quote_by_link(link: str) -> bool:
    quote = get_quote_by_link(link)
    if quote is None:
        return False
    delete_quote(quote)
    return True


def add_quote(
    chat: Chat | ChatData,
    user: User | UserData | Chat,
    qer: User | UserData | Chat,
    message: Message,
    link: str,
    img: str = None,
) -> Quote:
    """
    add quote if not exists

    :param chat: Chat or ChatData object
    :param user: 被 q 的人 User or UserData object
    :param qer: 使用 q 的人
    :param message: Message object
    :param img: str, 图片的 file_id, defaults to None
    """
    if quote := get_quote_by_link(link):
        return quote
    _db.add(
        Quote(
            chat_id=chat.id,
            user_id=user.id,
            message_id=message.message_id,
            link=link,
            qer_id=qer.id,
            text=message.text,
            img=img,
        )
    )
    commit()
    return get_quote_by_link(link)


def get_all_quotes_count() -> int:
    return _db.query(Quote).count()


def query_quote_user_can_see_by_text(
    user: User | UserData, text: str, limit: int = 10
) -> list[Quote]:
    return (
        _db.query(Quote)
        .filter(
            or_(
                Quote.chat_id.in_(
                    _db.query(ChatData.id).filter(
                        ChatData.members.any(UserData.id == user.id)
                    )
                ),
                Quote.user_id == user.id,
                Quote.qer_id == user.id,
            ),
            Quote.text.like(f"%{text}%"),
        )
        .order_by(func.random())
        .limit(limit)
        .all()
    )


def query_user_quote_by_text(
    user: User | UserData, text: str, limit: int = 10
) -> list[Quote]:
    return (
        _db.query(Quote)
        .filter(Quote.user_id == user.id, Quote.text.like(f"%{text}%"))
        .order_by(func.random())
        .limit(limit)
        .all()
    )


def query_qer_quote_by_text(
    user: User | UserData, text: str, limit: int = 10
) -> list[Quote]:
    return (
        _db.query(Quote)
        .filter(Quote.qer_id == user.id, Quote.text.like(f"%{text}%"))
        .order_by(func.random())
        .limit(limit)
        .all()
    )
