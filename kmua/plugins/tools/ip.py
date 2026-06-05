import contextlib
import ipaddress
from urllib.parse import urlparse

import httpx
import idna
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import Message

from kmua import common, database, i18n
from kmua.common.utils import is_explicit_reply
from kmua.logger import logger


@Client.on_message(filters.command("ip"), group=0)
async def ipinfo(client: Client, message: Message):
    user = message.from_user or message.sender_chat
    chat = message.chat
    in_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    if in_group:
        lang = (await database.get_chat_config(chat.id)).lang
    else:
        lang = (await database.get_user_config(user.id)).lang

    ip = None

    if is_explicit_reply(message) and message.reply_to_message:
        ip = message.reply_to_message.text or message.reply_to_message.caption

    if not ip and message.command and len(message.command) > 1:
        ip = message.command[1]

    if not ip:
        await message.reply_text(i18n.t("bot.msg.ip.no_ip_provided", locale=lang))
        return

    ip_parsed = urlparse(ip)
    ip = ip_parsed.hostname or ip_parsed.path or ip_parsed.netloc

    if not ip:
        await message.reply_text(i18n.t("bot.msg.ip.no_ip_provided", locale=lang))
        return

    if not _is_valid_ip_or_domain(ip):
        await message.reply_text(i18n.t("bot.msg.ip.no_ip_provided", locale=lang))
        return

    sent_message = await message.reply_text(
        i18n.t("bot.msg.ip.querying", locale=lang).format(ip=ip)
    )

    querying_key = f"ip_querying:{user.id}"
    if await common.memstore.get(querying_key):
        return
    try:
        await common.memstore.set(querying_key, True)
        result = await _get_ip_info(ip, lang)
        await sent_message.edit_text(text=result, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
        await sent_message.edit_text(
            i18n.t("bot.msg.ip.query_failed", locale=lang).format(
                error_type=e.__class__.__name__, error=str(e)
            )
        )
    finally:
        await common.memstore.delete(querying_key)


_DOMAIN_MAX_LEN = 253


def _is_valid_ip_or_domain(value: str) -> bool:
    """校验是否为合法的公网 IP 地址或域名, 防止 `.`、`localhost`、`127.1` 等触发本机/内网查询."""
    try:
        ip_obj = ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        return ip_obj.is_global and not ip_obj.is_multicast

    host = value.rstrip(".")
    if not host or len(host) > _DOMAIN_MAX_LEN or "." not in host:
        return False
    tld = host.rsplit(".", 1)[-1]
    if not any(c.isalpha() for c in tld):
        return False
    try:
        idna.encode(host, uts46=True)
    except idna.IDNAError:
        return False
    return True


async def _get_ip_info(url: str, lang: str) -> str:
    async with httpx.AsyncClient() as client:
        data = await client.get(
            url="http://ip-api.com/json/" + url,
            params={
                "fields": "status,message,country,regionName,"
                "city,lat,lon,isp,org,as,mobile,proxy,hosting,query"
            },
        )
    ipinfo_json = data.json()
    if ipinfo_json["status"] != "success":
        return i18n.t("bot.msg.ip.query_failed_reason", locale=lang).format(
            message=ipinfo_json["message"]
        )
    ipinfo_list = [i18n.t("bot.msg.ip.query_target", locale=lang).format(url=url)]
    if ipinfo_json["query"] != url:
        ipinfo_list.extend(
            [
                i18n.t("bot.msg.ip.resolved_address", locale=lang).format(
                    query=ipinfo_json["query"]
                )
            ]
        )
    ipinfo_list.extend(
        [
            i18n.t("bot.msg.ip.location", locale=lang).format(
                country=ipinfo_json["country"],
                region=ipinfo_json["regionName"],
                city=ipinfo_json["city"],
            ),
            i18n.t("bot.msg.ip.coordinates", locale=lang).format(
                lat=str(ipinfo_json["lat"]), lon=str(ipinfo_json["lon"])
            ),
            i18n.t("bot.msg.ip.isp", locale=lang).format(isp=ipinfo_json["isp"]),
        ]
    )
    if ipinfo_json["org"] != "":
        ipinfo_list.extend(
            [
                i18n.t("bot.msg.ip.organization", locale=lang).format(
                    org=ipinfo_json["org"]
                )
            ]
        )
    with contextlib.suppress(Exception):
        ipinfo_list.extend(
            [
                i18n.t("bot.msg.ip.as_number", locale=lang).format(
                    as_number=ipinfo_json["as"],
                    as_link=ipinfo_json["as"].split()[0],
                )
            ]
        )
    if ipinfo_json["mobile"]:
        ipinfo_list.extend([i18n.t("bot.msg.ip.mobile_ip", locale=lang)])
    if ipinfo_json["proxy"]:
        ipinfo_list.extend([i18n.t("bot.msg.ip.proxy_ip", locale=lang)])
    if ipinfo_json["hosting"]:
        ipinfo_list.extend([i18n.t("bot.msg.ip.hosting_ip", locale=lang)])
    return "\n".join(ipinfo_list)
