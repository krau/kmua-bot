import contextlib
from urllib.parse import urlparse

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from kmua.logger import logger


async def ipinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    text = message.text
    user = update.effective_user
    logger.info(f"[{update.effective_chat.title}]({user.name}) {text}")
    if context.user_data.get("ip_querying", False):
        return
    ip = None
    if target_message := message.reply_to_message:
        ip = target_message.text or target_message.caption
    if not ip:
        ip = context.args[0] if context.args else None
    if not ip:
        ip = context.user_data.get("ip_query")
    if not ip:
        await message.reply_text("请提供要查询的 IP/域名")
        return
    ip = urlparse(ip)
    ip = ip.hostname or ip.path or ip.netloc
    if not ip:
        await message.reply_text("请提供要查询的 IP/域名")
        return
    logger.info(f"查询: {ip}")
    sent_message = await message.reply_text(f"正在查询: {ip}")
    try:
        context.user_data["ip_querying"] = True
        await sent_message.edit_text(
            await _get_ip_info(ip), disable_web_page_preview=True, parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"查询失败: {e.__class__.__name__}: {e}")
        await sent_message.edit_text(f"查询失败: {e.__class__.__name__}: {e}")
    finally:
        context.user_data["ip_querying"] = False
        context.user_data["ip_query"] = None


async def _get_ip_info(url: str) -> str:
    """获取 IP 信息"""
    async with httpx.AsyncClient() as client:
        data = await client.get(
            url="http://ip-api.com/json/" + url,
            params={
                "fields": "status,message,country,regionName,"
                "city,lat,lon,isp,org,as,mobile,proxy,hosting,query"
            },
        )
    ipinfo_json = data.json()
    if ipinfo_json["status"] == "fail":
        return "查询失败: " + ipinfo_json["message"]
    if ipinfo_json["status"] == "success":
        ipinfo_list = [f"查询目标： `{url}`"]
        if ipinfo_json["query"] != url:
            ipinfo_list.extend(["解析地址： `" + ipinfo_json["query"] + "`"])
        ipinfo_list.extend(
            [
                (
                    (
                        "地区： `"
                        + ipinfo_json["country"]
                        + " - "
                        + ipinfo_json["regionName"]
                        + " - "
                        + ipinfo_json["city"]
                    )
                    + "`"
                ),
                "经纬度： `"
                + str(ipinfo_json["lat"])
                + ","
                + str(ipinfo_json["lon"])
                + "`",
                "ISP： `" + ipinfo_json["isp"] + "`",
            ]
        )
        if ipinfo_json["org"] != "":
            ipinfo_list.extend(["组织： `" + ipinfo_json["org"] + "`"])
        with contextlib.suppress(Exception):
            ipinfo_list.extend(
                [
                    "["
                    + ipinfo_json["as"]
                    + "](https://bgp.he.net/"
                    + ipinfo_json["as"].split()[0]
                    + ")"
                ]
            )
        if ipinfo_json["mobile"]:
            ipinfo_list.extend(["此 IP 可能为**蜂窝移动数据 IP**"])
        if ipinfo_json["proxy"]:
            ipinfo_list.extend(["此 IP 可能为**代理 IP**"])
        if ipinfo_json["hosting"]:
            ipinfo_list.extend(["此 IP 可能为**数据中心 IP**"])
        return "\n".join(ipinfo_list)
