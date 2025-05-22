from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class I18n:
    def __init__(
        self,
        locales_dir: Path = Path(__file__).parent / "locales",
        default_locale: str = "zh-CN",
    ):
        self.locales_dir = locales_dir
        self.default_locale = default_locale
        self.translations: Dict[str, Dict[str, Any]] = {}
        self.available_locales = set()

        self.load_translations()

    def load_translations(self):
        if not self.locales_dir.exists():
            raise FileNotFoundError(f"翻译目录 '{self.locales_dir}' 不存在")

        for locale_dir in self.locales_dir.iterdir():
            if locale_dir.is_dir():
                locale_name = locale_dir.name
                self.available_locales.add(locale_name)
                self.translations[locale_name] = {}
                self._load_locale_files(locale_dir, locale_name)

    def _load_locale_files(self, locale_dir: Path, locale_name: str):
        yaml_files = list(locale_dir.glob("**/*.yaml")) + list(
            locale_dir.glob("**/*.yml")
        )

        for yaml_file in yaml_files:
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if content:
                        self._merge_translations(
                            self.translations[locale_name], content
                        )
            except Exception as e:
                print(f"加载文件 {yaml_file} 时出错: {e}")

    def _merge_translations(self, target: Dict[str, Any], source: Dict[str, Any]):
        for key, value in source.items():
            if (
                isinstance(value, dict)
                and key in target
                and isinstance(target[key], dict)
            ):
                self._merge_translations(target[key], value)
            else:
                target[key] = value

    def _get_nested_value(self, data: Dict[str, Any], key: str) -> Optional[str]:
        keys = key.split(".")
        current = data

        try:
            for k in keys:
                current = current[k]
            return str(current) if current is not None else None
        except (KeyError, TypeError):
            return None

    def t(self, key: str, locale: str = "") -> str:
        """
        翻译指定的键

        Args:
            key: 翻译键, 使用点分隔的字符串表示嵌套
            locale: 目标语言

        Returns:
            翻译后的字符串，如果找不到则返回原键
        """
        if locale is None:
            locale = self.default_locale

        if locale not in self.translations:
            if self.default_locale in self.translations:
                locale = self.default_locale
            else:
                return key

        translation = self._get_nested_value(self.translations[locale], key)

        if translation is None and locale != self.default_locale:
            if self.default_locale in self.translations:
                translation = self._get_nested_value(
                    self.translations[self.default_locale], key
                )

        return translation if translation is not None else key

    def get_available_locales(self) -> list:
        return list(self.available_locales)

    def set_default_locale(self, locale: str):
        if locale in self.available_locales:
            self.default_locale = locale
        else:
            print(f"语言 '{locale}' 不可用")

    def reload(self):
        self.translations.clear()
        self.available_locales.clear()
        self.load_translations()


i18n = I18n()
t = i18n.t
