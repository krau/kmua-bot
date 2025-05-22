from .db import async_session
from .models import ChatData, UserChatAssociation, UserData


async def add_member_in_chat(
    chat: ChatData, user: UserData, waifu: UserData | None
) -> UserChatAssociation:
    async with async_session() as session:
        async with session.begin():
            if data := await session.get(UserChatAssociation, (user.id, chat.id)):
                return data
            member = UserChatAssociation(
                user_id=user.id,
                chat_id=chat.id,
                waifu_id=waifu.id if waifu else None,
            )
            session.add(member)
            await session.commit()
            return member
