import re
import os
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
            pass

    async def screenshot(self, url: str, width: int = 1280, height: int = 720, close: bool = True):
        """
        获取网页截屏

        :param url: 网址
        :param width: 页面宽度, defaults to 1280
        :param height: 页面高度, defaults to 720
        :param close: 完成后是否关闭网页, defaults to True
        """
        try:
            page = await self.new_page(url=url, width=width, height=height)
            file_nm = await self.get_mod_name(url=url, lang='en')
            file_nm = re.sub(r'[^a-zA-Z]', '', file_nm) + '.png'
            if not os.path.exists('./pics/'):
                os.makedirs('./pics/')
                logger.debug('未找到保存路径,已新建')
            if not os.path.exists(f'./pics/{file_nm}'):
                await page.screenshot({'path': f'./pics/{file_nm}'})
                logger.info(f'保存截屏{file_nm}成功')
            else:
                logger.debug(f'截屏文件{file_nm}已存在')
            if close:
                await page.close()
                logger.debug('关闭页面')
            return file_nm
        except Exception as e:
            logger.error(f'获取截屏 {url} 失败!')
            logger.error(f'错误类型:{e.__class__.__name__}')

    async def get_mod_name(self, url: str, lang: str = 'full', close: bool = True) -> str:
        """
        获取模组名

        :param url: mcmod的模组页面
        :param lang: 要获取的模组名语言, defaults to 'full'
        :param close: 完成后是否关闭网页, defaults to True
        :return:
        """
        try:
            page = await self.new_page(url=url)
            logger.debug(f'获取页面 {url} 元素')
            class_title = await page.waitForSelector(selector='.class-title')
            cn_nm = await(await(await class_title.querySelector('h3')).getProperty('innerText')).jsonValue()
            en_nm = await(await(await class_title.querySelector('h4')).getProperty('innerText')).jsonValue()
            full_nm = f'{cn_nm} | {en_nm}'
            logger.debug(f'获取模组名成功:{full_nm}')
            if close:
                await page.close()
                logger.debug('关闭页面')
            if lang == 'full':
                return full_nm
            elif lang == 'cn':
                return cn_nm
            elif lang == 'en':
                return en_nm
            else:
                logger.debug(f'lang不能为{lang}')
                return ''
        except Exception as e:
            logger.error(f'获取模组名称 {url} 失败!')
            logger.error(f'错误类型:{e.__class__.__name__}')
