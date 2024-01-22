import random

from telegram import Update
from telegram.ext import ContextTypes

from kmua import common
from kmua.logger import logger

from .jobs import send_message


async def ohayo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"ohayo {update.effective_user.name}")
    if context.job_queue.get_jobs_by_name(f"ohayo_{update.effective_user.id}"):
        logger.debug(f"job ohayo_{update.effective_user.id} 已存在")
        return
    context.job_queue.run_once(
        callback=send_message,
        when=random.randint(22, 25) * random.randint(3500, 3600),
        data={
            "chat_id": update.effective_user.id,
            "text": random.choice(common.ohayo_word),
        },
        name=f"ohayo_{update.effective_user.id}",
    )


async def oyasumi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"oyasumi {update.effective_user.name}")
    if context.job_queue.get_jobs_by_name(f"oyasumi_{update.effective_user.id}"):
        logger.debug(f"job oyasumi_{update.effective_user.id} 已存在")
        return
    context.job_queue.run_once(
        callback=send_message,
        when=random.randint(22, 25) * random.randint(3500, 3600),
        data={
            "chat_id": update.effective_user.id,
            "text": random.choice(common.oyasumi_word),
        },
        name=f"oyasumi_{update.effective_user.id}",
    )
