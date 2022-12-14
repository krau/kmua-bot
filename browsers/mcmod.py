import re
import os
import json
from pyppeteer.launcher import launch
from pyppeteer.browser import Page
from src.logger import Logger

logger = Logger(name='McMod', show=True)


class McMod:
    def __init__(self, width: int = 1280, height: int = 1080) -> None:
        """
        参数设定

        :param width: 页面宽度, defaults to 1280
        :param height: 页面高度, defaults to 1080
        """
        logger.debug('实例化McMod')
        self.args = ['--headless', '--no-sandbox',
                     '--disable-gpu', '--hide-scrollbars']
        self.options = {'args': self.args, 'defaultViewport': {
            'width': width, 'height': height}}

    async def new_page(self, url: str = '', width: int = 1280, height: int = 720) -> Page:
        """
        启动浏览器并新建页面

        :param url: 网址,如果为空则只启动浏览器, defaults to ''
        :param width: 页面宽度, defaults to 1280
        :param height: 页面高度, defaults to 720
        :return: Page类
        """
        try:
            logger.debug(f'新建页面 {url}')
            wb = await launch(options=self.options)
            page = await wb.newPage()
            await page.setViewport({'width': width, 'height': height})
            if url:
                await page.goto(url=url)
                logger.debug(f'页面已新建 {url}')
                return page
            else:
                logger.debug(f'未传入url,仅开启浏览器')
                return page
        except Exception as e:
            logger.error(f'新建页面 {url} 失败!')
            logger.error(f'错误类型:{e.__class__.__name__}')
            await page.close()

    async def screenshot(self, url: str, width: int = 1280, height: int = 720, close: bool = True) -> dict:
        """
        获取网页截屏

        :param url: 网址
        :param width: 页面宽度, defaults to 1280
        :param height: 页面高度, defaults to 720
        :param close: 完成后是否关闭网页, defaults to True
        :return: 文件名字典{'file_name':文件名,'cn_name':中文名,
                        'en_name':英文名,'full_name':格式化后的全名}
        """
        try:
            logger.debug(f'开始获取截屏:{url}')
            data_dict =  self.mod_data_read(mod_url=url)
            if data_dict:
                return data_dict
            else:
                page = await self.new_page(url=url, width=width, height=height)
                logger.debug(f'获取页面 {url} 元素')
                class_title = await page.waitForSelector(selector='.class-title')
                cn_nm = await(await(await class_title.querySelector('h3')).getProperty('innerText')).jsonValue()
                en_nm = await(await(await class_title.querySelector('h4')).getProperty('innerText')).jsonValue()
                logger.debug(f'获取元素成功:{cn_nm},{en_nm}')
                file_nm = re.sub(r'[^a-zA-Z]', '', en_nm) + '.png'  # 以英文模组名(去除非法字符)保存截屏文件
                full_nm = f'{cn_nm} | {en_nm}'  # 为了少开一次浏览器，干脆把模组名也顺便获取并返回
                logger.info(f'获取截屏:{file_nm}')
                if not os.path.exists('./pics/'):
                    os.makedirs('./pics/')
                    logger.debug('未找到截图保存路径,已新建')
                if not os.path.exists(f'./pics/{file_nm}'):
                    await page.screenshot({'path': f'./pics/{file_nm}'})
                    logger.info(f'保存截屏{file_nm}成功')
                else:
                    logger.info(f'截屏文件{file_nm}已存在')
                if close:
                    await page.close()
                    logger.debug('关闭页面')
                data_dict = {'file_name': file_nm, 'cn_name': cn_nm,
                            'en_name': en_nm, 'full_name': full_nm,'mod_url':url}
                self.mod_data_record(mod_cn_name=cn_nm,mod_en_name=en_nm,mod_file_name=file_nm,mod_full_name=full_nm,mod_url=url)
                return data_dict
        except Exception as e:
            logger.error(f'获取截屏 {url} 失败!')
            logger.error(f'错误类型:{e.__class__.__name__}')
            await page.close()
            return {}

    async def get_mod_name(self, url: str, lang: str = 'full', close: bool = True) -> str:
        """
        获取模组名

        :param url: mcmod的模组页面
        :param lang: 要获取的模组名语言, defaults to 'full'
        :param close: 完成后是否关闭网页, defaults to True
        :return:
        """
        try:
            logger.info(f'尝试获取模组名:{url}')
            page = await self.new_page(url=url)
            logger.debug(f'获取页面 {url} 元素')
            class_title = await page.waitForSelector(selector='.class-title')
            cn_nm = await(await(await class_title.querySelector('h3')).getProperty('innerText')).jsonValue()
            en_nm = await(await(await class_title.querySelector('h4')).getProperty('innerText')).jsonValue()
            full_nm = f'{cn_nm} | {en_nm}'
            logger.info(f'获取模组名成功:{full_nm}')
            if close:
                await page.close()
                logger.debug('关闭页面')
            if lang == 'full':
                return full_nm
            elif lang == 'cn':
                return cn_nm
            elif lang == 'en':
                return en_nm
            elif lang == 'dict':
                name_dict = {'cn_name':cn_nm,'en_name':en_nm,'full_name':full_nm}
                return name_dict
            else:
                logger.debug(f'lang不能为{lang}')
                return ''
        except Exception as e:
            logger.error(f'获取模组名称 {url} 失败!')
            logger.error(f'错误类型:{e.__class__.__name__}')
            return ''

    def mod_data_record(self, mod_file_name: str, mod_cn_name: str, mod_en_name: str, mod_full_name: str, mod_url: str, mod_pic_path: str = ''):
        try:
            logger.debug(f'记录模组数据:{mod_cn_name}')
            mods_data_path = './data/mods_data.json'
            if not os.path.exists(mods_data_path):
                with open(mods_data_path, 'w',encoding='utf-8') as f:
                    json.dump({}, f,ensure_ascii=False)
                logger.debug(f'未找到数据文件路径,已新建')
            if not mod_pic_path:
                mod_pic_path = f'./pics/{mod_file_name}'
                logger.debug(f'未传入pic_path,使用默认:{mod_pic_path}')
            mod_data = {mod_url: {'file_name': mod_file_name, 'cn_name': mod_cn_name,
                                        'en_name': mod_en_name, 'full_name': mod_full_name, 'mod_url': mod_url, 'pic_path': mod_pic_path}}
            logger.debug(f'模组数据:{mod_data}')
            with open(mods_data_path,'r',encoding='utf-8') as f:
                data_content = json.load(f)
            data_content.update(mod_data)
            with open(mods_data_path,'w',encoding='utf-8') as f:
                json.dump(data_content,f,indent=4,ensure_ascii=False)
            logger.info(f'已记录模组数据:{mod_data}')
            return True
        except Exception as e:
            logger.error(f'记录模组数据 {mod_cn_name} 错误!')
            logger.error(f'错误类型:{e.__class__.__name__}')
            return False

    def mod_data_read(self,mod_url:str) -> dict:
        try:
            logger.debug(f'读取模组数据:{mod_url}')
            mods_data_path = './data/mods_data.json'
            if not os.path.exists(mods_data_path):
                logger.debug('模组数据文件不存在')
                return False
            with open(mods_data_path,'r',encoding='utf-8') as f:
                data = json.load(f)
            if mod_url in data:
                cn_name = data[mod_url].get('cn_name')
                logger.info(f'该模组数据已记录过:{cn_name}')
                return data[mod_url]
            else:
                logger.debug('模组数据未记录过')
                return False
        except Exception as e:
            logger.error(f'读取模组数据 {mod_url} 错误!')
            logger.error(f'错误类型:{e.__class__.__name__}')
            return False