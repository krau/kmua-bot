import json

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from kmua import i18n


def _permission_button(
    permission: str, enabled: bool, lang: str = "zh-CN"
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        i18n.t(f"bot.button.title_permissions.{permission}", locale=lang)
        + ("✅" if enabled else "❌"),
        callback_data=f"set_title_permissions {permission}",
    )


class TitlePermissionsMarkup:
    def __init__(self, permissions: dict[str, bool] = {}, lang: str = "zh-CN") -> None:
        self.lang = lang
        if isinstance(permissions, str):
            permissions = json.loads(permissions)
        self.permissions = permissions

    def build(self) -> InlineKeyboardMarkup:
        permission_groups = [
            ["can_change_info", "can_delete_messages", "can_manage_tags"],
            ["can_restrict_members", "can_invite_users", "can_promote_members"],
            ["can_post_stories", "can_edit_stories", "can_delete_stories"],
            ["can_manage_video_chats", "can_manage_topics", "can_pin_messages"],
        ]

        keyboard = []
        for row in permission_groups:
            keyboard_row = []
            for permission in row:
                enabled = self.permissions.get(permission, False)
                keyboard_row.append(_permission_button(permission, enabled, self.lang))
            keyboard.append(keyboard_row)

        return InlineKeyboardMarkup(keyboard)
