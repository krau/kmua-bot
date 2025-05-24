from kmua import common, database, enums

from .client import client


async def cleanup():
    try:
        await common.memstore.set(enums.GLockKey.CLEANING, True)
        await database.cleanup_waifu_data()
    finally:
        await common.memstore.delete(enums.GLockKey.CLEANING)
