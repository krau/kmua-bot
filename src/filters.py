from telegram import Update
from telegram.ext.filters import (
    UpdateFilter,
    FilterDataDict,
)


class StartFilter(UpdateFilter):
    def filter(self, update:Update) -> bool | FilterDataDict | None:
        if (
            update.effective_chat.type != "private"
            and update.effective_message.text == "/start"
        ):
            return False
        return True


start_filter = StartFilter()
