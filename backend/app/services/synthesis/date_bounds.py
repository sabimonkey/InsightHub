"""Calendar-day bounds for brief filters (local app timezone → UTC instants)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings


def app_timezone(settings: Settings | None = None) -> ZoneInfo:
    settings = settings or get_settings()
    name = (getattr(settings, "insighthub_app_timezone", None) or "Asia/Shanghai").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Asia/Shanghai")


def calendar_range_utc(start_date: date, end_date: date, settings: Settings | None = None) -> tuple[datetime, datetime]:
    """Inclusive local calendar start/end dates → [start, end) in UTC."""
    tz = app_timezone(settings)
    start = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, end
