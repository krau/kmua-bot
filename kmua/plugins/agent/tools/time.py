"""时间工具: 查询当前时间或计算两个时间之间的差值。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic_ai import RunContext

from .. import datatype

# Any IANA timezone name is accepted; "local" and "UTC" are special-cased.
TimezoneName = str


@dataclass
class _NowResult:
    success: bool = True
    message: str = ""
    iso_format: str = ""
    readable_format: str = ""
    timezone: str = ""


@dataclass
class _DifferenceResult:
    success: bool = True
    message: str = ""


async def _now(
    timezone_name: TimezoneName, format_type: Literal["iso", "readable", "both"]
) -> _NowResult:
    from zoneinfo import ZoneInfo, available_timezones

    try:
        utc_now = datetime.now(UTC)
        if timezone_name == "UTC":
            target_time = utc_now
            tz_info = UTC
        elif timezone_name == "local":
            target_time = datetime.now()
            tz_info = target_time.astimezone().tzinfo
            target_time = target_time.replace(tzinfo=tz_info)
        else:
            if timezone_name in available_timezones():
                tz_info = ZoneInfo(timezone_name)
                target_time = utc_now.astimezone(tz_info)
            else:
                target_time = datetime.now()
                tz_info = target_time.astimezone().tzinfo
                target_time = target_time.replace(tzinfo=tz_info)

        iso_str = target_time.isoformat()
        weekdays = [
            "星期一",
            "星期二",
            "星期三",
            "星期四",
            "星期五",
            "星期六",
            "星期日",
        ]
        weekday = weekdays[target_time.weekday()]
        readable_str = target_time.strftime(f"%Y年%m月%d日 %H:%M:%S {weekday}")

        if format_type == "iso":
            message = f"当前时间 (ISO): {iso_str}"
        elif format_type == "readable":
            message = f"当前时间: {readable_str}"
        else:
            message = f"当前时间:\n- ISO格式: {iso_str}\n- 易读格式: {readable_str}"

        return _NowResult(
            success=True,
            message=message,
            iso_format=iso_str,
            readable_format=readable_str,
            timezone=str(tz_info) if tz_info else "Unknown",
        )
    except Exception as e:
        return _NowResult(success=False, message=f"获取时间失败: {e}")


async def _difference(time1: str, time2: str) -> _DifferenceResult:
    from dateutil import parser

    try:
        dt1 = parser.parse(time1)
        dt2 = parser.parse(time2)
        if dt1.tzinfo is None:
            dt1 = dt1.replace(tzinfo=datetime.now().astimezone().tzinfo)
        if dt2.tzinfo is None:
            dt2 = dt2.replace(tzinfo=datetime.now().astimezone().tzinfo)
        diff = dt2 - dt1
        total_seconds = abs(diff.total_seconds())
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0:
            parts.append(f"{minutes}分钟")
        if seconds > 0 or not parts:
            parts.append(f"{seconds}秒")
        time_diff_str = "".join(parts)
        direction = "之后" if diff.total_seconds() >= 0 else "之前"
        message = (
            f"时间差: {time_diff_str}\n"
            f"{time1} 是 {time2} 的{direction}\n"
            f"总计: {abs(diff.total_seconds()):.0f} 秒"
        )
        return _DifferenceResult(success=True, message=message)
    except Exception as e:
        return _DifferenceResult(success=False, message=f"计算时间差失败: {e}")


async def time_info(
    ctx: RunContext[datatype.ContextDeps],
    operation: Literal["now", "difference"] = "now",
    time1: str | None = None,
    time2: str | None = None,
    timezone_name: TimezoneName = "local",
    format_type: Literal["iso", "readable", "both"] = "both",
) -> str:
    """Get the current date and time, or the gap between two timestamps.

    Args:
        operation: "now" reads the current time; "difference" compares two times.
        time1, time2: Required for "difference" — timestamps in ISO format
            (e.g. "2026-08-02T10:00:00+08:00") or natural strings such as
            "2026-08-02 10:00" or "now"; formats are detected automatically.
        timezone_name: The timezone "now" is reported in — "local" (default)
            is the bot's timezone, or any IANA name like "Asia/Shanghai",
            "Europe/Berlin". Ignored for "difference".
        format_type: How "now" is formatted: "iso", "readable", or "both" (default).
    """
    if operation == "now":
        result = await _now(timezone_name, format_type)
        if not result.success:
            return f"Error: {result.message}"
        return result.message
    if time1 is None or time2 is None:
        return "Error: operation 'difference' requires both time1 and time2."
    result = await _difference(time1, time2)
    if not result.success:
        return f"Error: {result.message}"
    return result.message


__all__ = ["time_info"]
