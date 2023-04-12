import json
import os
import re

from playwright.async_api import async_playwright

from src.logger import logger


class McMod:
    def __init__(self, width: int = 1280, height: int = 1080) -> None:
        """
        参数设定

        :param width: 页面宽度, defaults to 1280
        :param height: 页面高度, defaults to 1080
        """
        logger.debug("实例化McMod")
        self.args = ["--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars"]
        self.options = {
            "args": self.args,
            "defaultViewport": {"width": width, "height": height},
            "dumpio": True,
        }

    async def screenshot(
        self, mod_url: str, width: int = 1280, height: int = 720, close: bool = True
    ) -> dict:
        """
        获取网页截屏

        :param url: 网址
        :param width: 页面宽度, defaults to 1280
        :param height: 页面高度, defaults to 720
        :param close: 完成后是否关闭网页, defaults to True
        :return: 字典{'file_name':截图文件名,'cn_name':中文名,
                        'en_name':英文名,'full_name':格式化后的全名,'mod_url':模组链接}
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.set_viewport_size({"width": width, "height": height})
                await page.goto(mod_url)
                await page.wait_for_selector(".class-title")
                class_title = await page.query_selector(".class-title")
                try:
                    h4 = await class_title.query_selector("h4")
                    en_name = await h4.get_property("innerText")
                    en_name = await en_name.json_value()
                    try:
                        h3 = await class_title.query_selector("h3")
                        cn_name = await h3.get_property("innerText")
                        cn_name = await cn_name.json_value()
                    except Exception:
                        cn_name = ""
                except Exception:
                    en_name = ""
                    cn_name = ""
                # 以英文模组名(去除非法字符)保存截屏文件
                file_name = re.sub(r"[^a-zA-Z]", "", en_name) + ".png"
                full_name = f"{cn_name} {en_name}"  # 为了少开一次浏览器，干脆把模组名也顺便获取并返回
                if not os.path.exists(f"./data/pics/{file_name}"):
                    await page.screenshot(path=f"./data/pics/{file_name}")
                if close:
                    await page.close()
                    await browser.close()
                record_flag = self.mod_data_record(
                    mod_cn_name=cn_name,
                    mod_en_name=en_name,
                    mod_file_name=file_name,
                    mod_full_name=full_name,
                    mod_url=mod_url,
                )
                if record_flag:
                    data_dict = self.mod_data_read(mod_url=mod_url)
                    return data_dict
                else:
                    logger.error(f"未能记录模组 {mod_url}")
                    return {}
        except Exception as e:
            logger.error(f"获取截屏 {mod_url} 失败!")
            logger.error(f"错误:{e}")
            if close:
                await page.close()
                await browser.close()
            return {}

    async def get_mod_name(
        self, url: str, lang: str = "full", close: bool = True
    ) -> str:
        """
        获取模组名

        :param url: mcmod的模组页面
        :param lang: 要获取的模组名语言, defaults to 'full'
        :param close: 完成后是否关闭网页, defaults to True
        :return:
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(url)
                await page.wait_for_selector(".class-title")
                class_title = await page.query_selector(".class-title")
                try:
                    h4 = await class_title.query_selector("h4")
                    en_name = await h4.get_property("innerText")
                    en_name = await en_name.json_value()
                    try:
                        h3 = await class_title.query_selector("h3")
                        cn_name = await h3.get_property("innerText")
                        cn_name = await cn_name.json_value()
                    except Exception:
                        cn_name = ""
                except Exception:
                    en_name = ""
                    cn_name = ""
                full_nm = f"{cn_name} {en_name}"
                if close:
                    await page.close()
                    await browser.close()
                if lang == "full":
                    return full_nm
                elif lang == "cn":
                    return cn_name
                elif lang == "en":
                    return en_name
                elif lang == "dict":
                    name_dict = {
                        "cn_name": cn_name,
                        "en_name": en_name,
                        "full_name": full_nm,
                    }
                    return name_dict
                else:
                    logger.debug(f"lang不能为{lang}")
                    return ""
        except Exception as e:
            logger.error(f"获取模组名称 {url} 失败!")
            logger.error(f"错误:{e}")
            return ""

    def mod_data_record(
        self,
        mod_file_name: str,
        mod_full_name: str,
        mod_url: str,
        mod_cn_name: str = "",
        mod_en_name: str = "",
        mod_pic_path: str = "",
    ) -> bool:
        """
        以json文件存储模组的信息,变量名定义与其他函数中一致

        :param mod_file_name: 模组去除非法字符(包括空格)的英文全名+后缀名
        :param mod_full_name: 格式化后的全名, ex: 植物魔法|Botania
        :param mod_url: 模组链接
        :param mod_cn_name: 模组中文名, defaults to ''
        :param mod_en_name: 模组英文名, defaults to ''
        :param mod_pic_path: 模组页面截图路径, defaults to ''
        :return: 记录成功返回True,否则False
        """
        logger.debug("调用:McMod.mod_data_record")
        try:
            logger.debug(f"记录模组数据:{mod_cn_name}")
            mods_data_path = "./data/mods_data.json"
            if not os.path.exists(mods_data_path):
                with open(mods_data_path, "w", encoding="utf-8") as f:
                    json.dump({}, f, ensure_ascii=False)
                logger.debug("未找到数据文件路径,已新建")
            if not mod_pic_path:
                mod_pic_path = f"./data/pics/{mod_file_name}"
                logger.debug(f"未传入pic_path,使用默认:{mod_pic_path}")
            mod_data = {
                mod_url: {
                    "file_name": mod_file_name,
                    "cn_name": mod_cn_name,
                    "en_name": mod_en_name,
                    "full_name": mod_full_name,
                    "mod_url": mod_url,
                    "pic_path": mod_pic_path,
                }
            }
            logger.debug(f"模组数据:{mod_data}")
            with open(mods_data_path, "r", encoding="utf-8") as f:
                data_content = json.load(f)
            data_content.update(mod_data)
            with open(mods_data_path, "w", encoding="utf-8") as f:
                json.dump(data_content, f, indent=4, ensure_ascii=False)
            logger.info(f"已记录模组数据:{mod_data}")
            return True
        except Exception as e:
            logger.error(f"记录模组数据 {mod_url} 错误!")
            logger.error(f"错误:{e}")
            return False

    def mod_data_read(self, mod_url: str) -> dict:
        try:
            logger.debug(f"读取模组数据:{mod_url}")
            mods_data_path = "./data/mods_data.json"
            if not os.path.exists(mods_data_path):
                with open(mods_data_path, "w", encoding="utf-8") as f:
                    json.dump({}, f, ensure_ascii=False)
                logger.debug("未找到数据文件路径,已新建")
            with open(mods_data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if mod_url in data:
                full_name = data[mod_url].get("full_name")
                logger.info(f"该模组数据已记录:{full_name}")
                return data[mod_url]
            else:
                logger.debug("该模组数据未记录")
                return False
        except Exception as e:
            logger.error(f"读取模组数据 {mod_url} 错误!")
            logger.error(f"错误:{e}")
            return False
