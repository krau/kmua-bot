import re

import httpx
from telegram import File, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common
from kmua.config import settings
from kmua.logger import logger

_real_esrgan_api = settings.get("real_esrgan_api")
_real_esrgan_token = settings.get("real_esrgan_token")
_enabled = _real_esrgan_api and _real_esrgan_token
if _enabled:
    httpx_cilent = httpx.AsyncClient(
        base_url=_real_esrgan_api,
        headers={"X-Token": _real_esrgan_token, "User-Agent": "kmua/2.3.3"},
        timeout=60,
    )


async def super_resolute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _enabled:
        await update.effective_message.reply_text("没有启用该功能呢")
        return
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    logger.info(f"[{chat.title}]({user.name})<super_resolute>")

    if context.args:
        task_id = context.args[0]
        if not re.match(r"^\d+-\d+$", task_id):
            await message.reply_text("请不要输入奇怪的东西")
            return
        if common.redis_client:
            file_id = common.redis_client.get(f"kmua_sr_{task_id}")
            if file_id:
                await message.reply_document(
                    document=file_id.decode("utf-8"), filename=f"sr_{task_id}.png"
                )
                return
        try:
            response = await httpx_cilent.get(f"/result/{task_id}")
        except Exception as e:
            logger.error(f"{e.__class__.__name__}: {e}")
            await message.reply_text("查询超分结果失败惹, 请稍后再试试")
            return
        if response.status_code != 200:
            if response.status_code == 404:
                await message.reply_text("没找到对应的任务, 可能已经过期了")
                return
            await message.reply_text(
                f"查询超分结果失败惹, 请稍后再试试\n{response.status_code}"
            )
        result = response.json().get("result")
        result_status = result.get("status")
        match result_status:
            case "failed":
                await message.reply_text("这张图片处理失败了...")
            case "pending":
                await message.reply_text("这张图片还在排队...")
            case "processing":
                await message.reply_text("这张图片正在处理中...")
            case "success":
                _clean_jobs(context, task_id)
                await message.reply_text("正在下载超分结果...")
                try:
                    resp = await httpx_cilent.get(f"/result/{task_id}/download")
                except Exception as e:
                    logger.error(e)
                    await message.reply_text(f"下载超分结果失败: {e}")
                    return
                if resp.status_code != 200:
                    await message.reply_text(f"下载超分结果失败: {resp.status_code}")
                    return
                try:
                    document_message = await message.reply_document(
                        document=resp.content, filename=f"sr_{task_id}.png"
                    )
                    if common.redis_client:
                        common.redis_client.set(
                            f"kmua_sr_{task_id}",
                            f"{document_message.document.file_id}",
                            ex=86400,
                        )
                except Exception as e:
                    logger.error(e)
                    await message.reply_text(f"发送超分结果失败: {e}")
                    return
            case _:
                await message.reply_text(f"服务器返回了奇怪的东西!\n {result_status}")
        return

    target_message = message.reply_to_message
    if not (target_message and (target_message.photo or target_message.document)):
        await message.reply_text("请回复一张图片")
        return

    photo_file: File = None
    sent_message = await message.reply_text("正在下载图片...")
    try:
        if target_message.photo:
            photo_file = await target_message.photo[-1].get_file()
        elif target_message.document and target_message.document.mime_type.startswith(
            "image"
        ):
            if target_message.document.file_size > 2 * 1024 * 1024:
                await sent_message.edit_text("文件太大了! 不行!")
                return
            photo_file = await target_message.document.get_file()
        else:
            await sent_message.edit_text("请回复一张图片")
            return
        photo_bytes = bytes(await photo_file.download_as_bytearray())
    except Exception as e:
        logger.error(e)
        await sent_message.edit_text("下载图片失败")
        return
    try:
        response = await httpx_cilent.post(
            "/sr",
            files={"file": ("image.jpg", photo_bytes, "image/jpeg")},
        )
    except Exception as e:
        logger.error(e)
        await sent_message.edit_text("服务器坏掉了喵, 超分失败")
        return
    if response.status_code != 200:
        await sent_message.edit_text("服务器坏掉了喵, 超分失败")
        return
    task_id = response.json().get("task_id")
    await sent_message.edit_text(
        f"{escape_markdown("超分任务已经提交, ID: ",2)}`{escape_markdown(task_id,2)}`\n请过段时间来取结果哦",
        parse_mode="MarkdownV2",
    )
    context.job_queue.run_repeating(
        _check_super_resolute_result,
        interval=30,
        first=0,
        last=settings.get("real_esrgan_timeout", 600),
        chat_id=chat.id,
        user_id=user.id,
        data={"task_id": task_id, "message_id": target_message.message_id},
        name=f"check_super_resolute_result_{task_id}",
    )


async def _check_super_resolute_result(context: ContextTypes.DEFAULT_TYPE):
    task_id = context.job.data.get("task_id")
    chat_id = context.job.chat_id
    message_id = context.job.data.get("message_id")
    try:
        resp = await httpx_cilent.get(f"/result/{task_id}")
    except Exception as e:
        logger.error(f"check_super_resolute_result: {e}")
        return
    if resp.status_code != 200:
        logger.warning(f"check super resolute result failed. code: {resp.status_code}")
        if resp.status_code == 404:
            _clean_jobs(context, task_id)
        return
    result = resp.json().get("result")
    if result.get("status") == "failed":
        _clean_jobs(context, task_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="这张图片处理失败了...",
            reply_to_message_id=message_id,
        )
        return
    if result.get("status") != "success":
        return

    _clean_jobs(context, task_id)

    try:
        resp = await httpx_cilent.get(f"/result/{task_id}/download")
    except Exception as e:
        logger.error(f"download_super_resolute_result: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"下载超分结果失败, 可以手动重试1下看看:\n/sr {task_id}",
            reply_to_message_id=message_id,
        )
        return
    if resp.status_code != 200:
        logger.warning("download super resolute result failed")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"下载超分结果失败, 可以手动重试1下看看:\n/sr {task_id}",
            reply_to_message_id=message_id,
        )
        return
    try:
        document_message = await context.bot.send_document(
            chat_id=chat_id,
            document=resp.content,
            reply_to_message_id=message_id,
            filename=f"sr_{task_id}.png",
            read_timeout=60,
            write_timeout=60,
        )
        if common.redis_client:
            common.redis_client.set(
                f"kmua_sr_{task_id}", f"{document_message.document.file_id}", ex=86400
            )
    except Exception as e:
        logger.error(f"send_document: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"发送超分结果失败: {e}",
            reply_to_message_id=message_id,
        )
        return


def _clean_jobs(context: ContextTypes.DEFAULT_TYPE, task_id: str):
    for job in context.job_queue.get_jobs_by_name(
        f"check_super_resolute_result_{task_id}"
    ):
        job.schedule_removal()
