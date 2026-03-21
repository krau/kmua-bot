"""时间相关工具"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic_ai import RunContext

from .. import datatype


@dataclass
class CurrentTimeResult:
    """当前时间结果"""

    success: bool = True
    message: str = ""
    iso_format: str = ""
    readable_format: str = ""
    timezone: str = ""


async def get_current_time(
    ctx: RunContext[datatype.ContextDeps],
    timezone_name: Literal[
        "local",
        "UTC",
        "Asia/Shanghai",
        "Asia/Tokyo",
        "America/New_York",
        "Europe/London",
    ] = "local",
    format_type: Literal["iso", "readable", "both"] = "both",
) -> CurrentTimeResult:
    """获取当前时间和日期信息。

    当你需要知道当前时间、计算时间差或回答与时间相关的问题时使用此工具。

    Args:
        timezone_name: 时区选择
            - "local": 系统本地时间
            - "UTC": 协调世界时
            - "Asia/Shanghai": 中国标准时间 (UTC+8)
            - "Asia/Tokyo": 日本标准时间 (UTC+9)
            - "America/New_York": 美国东部时间
            - "Europe/London": 格林尼治时间
        format_type: 返回格式
            - "iso": ISO 8601 格式 (如: 2025-03-21T15:30:00+08:00)
            - "readable": 易读格式 (如: 2025年3月21日 15:30:00 星期五)
            - "both": 同时返回两种格式

    Returns:
        CurrentTimeResult 包含当前时间信息
    """
    from zoneinfo import ZoneInfo, available_timezones

    try:
        # 获取当前 UTC 时间
        utc_now = datetime.now(UTC)

        # 根据时区名称获取对应时间
        if timezone_name == "UTC":
            target_time = utc_now
            tz_info = UTC
        elif timezone_name == "local":
            # 使用系统本地时区
            target_time = datetime.now()
            tz_info = target_time.astimezone().tzinfo
            target_time = target_time.replace(tzinfo=tz_info)
        else:
            # 使用指定的时区
            if timezone_name in available_timezones():
                tz_info = ZoneInfo(timezone_name)
                target_time = utc_now.astimezone(tz_info)
            else:
                # 如果时区不可用，回退到本地时间
                target_time = datetime.now()
                tz_info = target_time.astimezone().tzinfo
                target_time = target_time.replace(tzinfo=tz_info)

        # 生成 ISO 格式
        iso_str = target_time.isoformat()

        # 生成易读格式
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

        # 根据 format_type 构建返回消息
        if format_type == "iso":
            message = f"当前时间 (ISO): {iso_str}"
        elif format_type == "readable":
            message = f"当前时间: {readable_str}"
        else:  # both
            message = f"当前时间:\n- ISO格式: {iso_str}\n- 易读格式: {readable_str}"

        return CurrentTimeResult(
            success=True,
            message=message,
            iso_format=iso_str,
            readable_format=readable_str,
            timezone=str(tz_info) if tz_info else "Unknown",
        )

    except Exception as e:
        return CurrentTimeResult(
            success=False,
            message=f"获取时间失败: {e}",
            iso_format="",
            readable_format="",
            timezone="",
        )


@dataclass
class TimeCalculationResult:
    """时间计算结果"""

    success: bool = True
    message: str = ""


async def calculate_time_difference(
    ctx: RunContext[datatype.ContextDeps],
    time1: str,
    time2: str,
    time_format: Literal["iso", "auto"] = "auto",
) -> TimeCalculationResult:
    """计算两个时间之间的时间差。

    Args:
        time1: 第一个时间字符串
        time2: 第二个时间字符串
        time_format: 时间格式
            - "iso": ISO 8601 格式
            - "auto": 自动检测格式

    Returns:
        TimeCalculationResult 包含时间差信息
    """
    from dateutil import parser

    try:
        # 解析时间
        if time_format == "iso":
            dt1 = datetime.fromisoformat(time1)
            dt2 = datetime.fromisoformat(time2)
        else:
            dt1 = parser.parse(time1)
            dt2 = parser.parse(time2)

        # 确保都有时区信息
        if dt1.tzinfo is None:
            dt1 = dt1.replace(tzinfo=datetime.now().astimezone().tzinfo)
        if dt2.tzinfo is None:
            dt2 = dt2.replace(tzinfo=datetime.now().astimezone().tzinfo)

        # 计算时间差
        diff = dt2 - dt1
        total_seconds = abs(diff.total_seconds())

        # 转换为易读格式
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)

        # 构建结果字符串
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

        return TimeCalculationResult(success=True, message=message)

    except Exception as e:
        return TimeCalculationResult(success=False, message=f"计算时间差失败: {e}")
