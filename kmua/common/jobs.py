import datetime
from typing import Any, Callable, Dict, Optional, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger


class _TaskScheduler:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._jobs: Dict[str, Any] = {}

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
        kwargs: Optional[dict] = None,
    ) -> None:
        trigger = DateTrigger(run_date=run_date)
        job = self._scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        self._jobs[job_id] = job

    def add_interval_job(
        self,
        job_id: str,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        trigger = IntervalTrigger(
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        job = self._scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        self._jobs[job_id] = job

    def add_daily_job(
        self,
        job_id: str,
        func: Callable,
        hour: Union[int, str] = 0,
        minute: Union[int, str] = 0,
        second: Union[int, str] = 0,
        timezone: datetime.tzinfo = datetime.timezone(datetime.timedelta(hours=8)),
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            second=second,
            timezone=timezone,
            start_date=start_date,
            end_date=end_date,
        )
        job = self._scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        self._jobs[job_id] = job

    def remove_job(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._scheduler.remove_job(job_id)
            del self._jobs[job_id]


jobqueue = _TaskScheduler()

__all__ = ["jobqueue"]
