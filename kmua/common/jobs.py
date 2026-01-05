import datetime
from collections.abc import Callable

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from kmua.logger import logger


class _TaskScheduler:
    # [TODO] persistent job store
    def __init__(self):
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)

    def add_onetime_job(
        self,
        job_id: str,
        func: Callable,
        run_date: datetime.datetime,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> Job:
        trigger = DateTrigger(run_date=run_date)
        logger.debug(f"add one-time job: {job_id} at {run_date}")
        job = self._scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        return job

    def add_interval_job(
        self,
        job_id: str,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
        start_date: str | None = None,
        end_date: str | None = None,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> Job:
        trigger = IntervalTrigger(
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        logger.debug(
            f"add interval job: {job_id} every {seconds}s, {minutes}m, {hours}h, {days}d"
        )
        job = self._scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        return job

    def add_daily_job(
        self,
        job_id: str,
        func: Callable,
        hour: int | str = 0,
        minute: int | str = 0,
        second: int | str = 0,
        timezone: datetime.tzinfo = datetime.timezone(datetime.timedelta(hours=8)),
        start_date: str | None = None,
        end_date: str | None = None,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> Job:
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            second=second,
            timezone=timezone,
            start_date=start_date,
            end_date=end_date,
        )
        logger.debug(f"add daily job: {job_id} at {hour}:{minute}:{second} {timezone}")
        job = self._scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        return job

    def remove_job(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)
        logger.debug(f"Removed job: {job_id}")


jobqueue = _TaskScheduler()

__all__ = ["jobqueue"]
