import datetime
from collections.abc import Callable
from typing import Any

from apscheduler.job import Job
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from kmua.database.db import sync_engine
from kmua.logger import logger


class _TaskScheduler:
    """定时任务调度器

    使用 APScheduler 原生的 SQLAlchemyJobStore 实现任务持久化。
    任务会在数据库中持久存储，重启后自动恢复。

    对于无法序列化的任务（如嵌套函数），自动回退到内存存储并记录警告。
    """

    def __init__(self):
        # 配置持久化存储和内存回退存储
        jobstores = {
            "default": SQLAlchemyJobStore(
                engine=sync_engine,
            ),
            "memory": MemoryJobStore(),  # 内存回退存储
        }
        self._scheduler = AsyncIOScheduler(jobstores=jobstores)

    def _add_job_with_fallback(
        self,
        func: Callable,
        trigger,
        id: str,
        args: list | None = None,
        kwargs: dict | None = None,
        replace_existing: bool = True,
    ) -> Job:
        """添加任务，如果持久化失败则回退到内存存储

        Args:
            func: 任务函数
            trigger: 触发器
            id: 任务ID
            args: 位置参数
            kwargs: 关键字参数
            replace_existing: 是否替换已存在的任务

        Returns:
            APScheduler Job 实例
        """
        try:
            # 尝试添加到持久化存储
            job = self._scheduler.add_job(
                func=func,
                trigger=trigger,
                id=id,
                args=args or [],
                kwargs=kwargs or {},
                replace_existing=replace_existing,
                jobstore="default",
            )
            return job
        except ValueError as e:
            if "cannot be serialized" in str(e) or "could not be determined" in str(e):
                # 无法序列化，回退到内存存储
                logger.warning(
                    f"Job '{id}' cannot be serialized for persistent storage. "
                    f"Falling back to memory storage. Error: {e}"
                )
                job = self._scheduler.add_job(
                    func=func,
                    trigger=trigger,
                    id=f"{id}_memory",
                    args=args or [],
                    kwargs=kwargs or {},
                    replace_existing=replace_existing,
                    jobstore="memory",
                )
                logger.info(
                    f"Job '{id}' added to memory storage (will NOT survive restart)"
                )
                return job
            else:
                # 其他错误，重新抛出
                raise

    def start(self) -> None:
        """启动调度器

        APScheduler 会自动从数据库恢复已保存的任务
        """
        if not self._scheduler.running:
            self._scheduler.start()
            # 检查持久化存储状态
            jobstore = self._scheduler._jobstores.get("default")
            if jobstore:
                logger.success(
                    f"Job scheduler started with persistent storage ({jobstore.__class__.__name__})"
                )
                # 尝试列出存储中的任务数量
                try:
                    jobs = self._scheduler.get_jobs(jobstore="default")
                    logger.info(f"Loaded {len(jobs)} jobs from persistent storage")
                except Exception as e:
                    logger.warning(f"Could not list jobs from storage: {e}")
            else:
                logger.warning("Job scheduler started WITHOUT persistent storage")

    def shutdown(self, wait: bool = True) -> None:
        """关闭调度器"""
        self._scheduler.shutdown(wait=wait)
        logger.debug("Job scheduler shutdown")

    def add_onetime_job(
        self,
        job_id: str,
        func: Callable,
        run_date: datetime.datetime,
        args: list | None = None,
        kwargs: dict | None = None,
        replace_existing: bool = True,
    ) -> Job:
        """添加一次性任务

        Args:
            job_id: 任务唯一标识
            func: 任务函数
            run_date: 执行时间
            args: 位置参数
            kwargs: 关键字参数
            replace_existing: 是否替换已存在的同名任务

        Returns:
            APScheduler Job 实例
        """
        trigger = DateTrigger(run_date=run_date)
        logger.debug(f"add one-time job: {job_id} at {run_date}")

        return self._add_job_with_fallback(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace_existing,
        )

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
        replace_existing: bool = True,
    ) -> Job:
        """添加间隔任务

        Args:
            job_id: 任务唯一标识
            func: 任务函数
            seconds: 间隔秒数
            minutes: 间隔分钟数
            hours: 间隔小时数
            days: 间隔天数
            start_date: 开始时间
            end_date: 结束时间
            args: 位置参数
            kwargs: 关键字参数
            replace_existing: 是否替换已存在的同名任务

        Returns:
            APScheduler Job 实例
        """
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

        return self._add_job_with_fallback(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace_existing,
        )

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
        replace_existing: bool = True,
    ) -> Job:
        """添加每日任务

        Args:
            job_id: 任务唯一标识
            func: 任务函数
            hour: 小时
            minute: 分钟
            second: 秒
            timezone: 时区
            start_date: 开始日期
            end_date: 结束日期
            args: 位置参数
            kwargs: 关键字参数
            replace_existing: 是否替换已存在的同名任务

        Returns:
            APScheduler Job 实例
        """
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            second=second,
            timezone=timezone,
            start_date=start_date,
            end_date=end_date,
        )
        logger.debug(f"add daily job: {job_id} at {hour}:{minute}:{second} {timezone}")

        return self._add_job_with_fallback(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace_existing,
        )

    def remove_job(self, job_id: str) -> None:
        """移除任务

        Args:
            job_id: 任务唯一标识
        """
        # 先尝试从持久化存储移除
        try:
            self._scheduler.remove_job(job_id, jobstore="default")
            logger.debug(f"Removed job: {job_id}")
            return
        except Exception:
            pass

        # 再尝试从内存存储移除（回退的任务会加上 _memory 后缀）
        try:
            self._scheduler.remove_job(f"{job_id}_memory", jobstore="memory")
            logger.debug(f"Removed job from memory: {job_id}")
        except Exception:
            pass

    def get_job(self, job_id: str) -> Job | None:
        """获取任务

        Args:
            job_id: 任务唯一标识

        Returns:
            APScheduler Job 实例或 None
        """
        # 先尝试从持久化存储获取
        try:
            job = self._scheduler.get_job(job_id, jobstore="default")
            if job is not None:
                return job
        except Exception:
            pass

        # 再尝试从内存存储获取（回退的任务会加上 _memory 后缀）
        try:
            return self._scheduler.get_job(f"{job_id}_memory", jobstore="memory")
        except Exception:
            return None

    def get_all_jobs(self) -> list[Job]:
        """获取所有任务（包括持久化和内存存储）

        Returns:
            APScheduler Job 列表
        """
        jobs = []
        # 获取持久化存储的任务
        try:
            jobs.extend(self._scheduler.get_jobs(jobstore="default"))
        except Exception:
            pass
        # 获取内存存储的任务
        try:
            jobs.extend(self._scheduler.get_jobs(jobstore="memory"))
        except Exception:
            pass
        return jobs

    def pause_job(self, job_id: str) -> None:
        """暂停任务

        Args:
            job_id: 任务唯一标识
        """
        # 先尝试暂停持久化存储的任务
        try:
            self._scheduler.pause_job(job_id, jobstore="default")
            logger.debug(f"Paused job: {job_id}")
            return
        except Exception:
            pass

        # 再尝试暂停内存存储的任务
        try:
            self._scheduler.pause_job(f"{job_id}_memory", jobstore="memory")
            logger.debug(f"Paused job from memory: {job_id}")
        except Exception:
            pass

    def resume_job(self, job_id: str) -> None:
        """恢复任务

        Args:
            job_id: 任务唯一标识
        """
        # 先尝试恢复持久化存储的任务
        try:
            self._scheduler.resume_job(job_id, jobstore="default")
            logger.debug(f"Resumed job: {job_id}")
            return
        except Exception:
            pass

        # 再尝试恢复内存存储的任务
        try:
            self._scheduler.resume_job(f"{job_id}_memory", jobstore="memory")
            logger.debug(f"Resumed job from memory: {job_id}")
        except Exception:
            pass

    def modify_job(
        self,
        job_id: str,
        **changes: Any,
    ) -> Job:
        """修改任务

        Args:
            job_id: 任务唯一标识
            **changes: 要修改的属性

        Returns:
            修改后的 Job 实例
        """
        job = self._scheduler.modify_job(job_id, jobstore="default", **changes)
        logger.debug(f"Modified job: {job_id}")
        return job


jobqueue = _TaskScheduler()

__all__ = ["jobqueue"]
