from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.services.synthesis.date_bounds import calendar_range_utc


def test_calendar_range_uses_app_timezone_not_utc_midnight():
    settings = Settings(insighthub_app_timezone="Asia/Shanghai")
    start, end = calendar_range_utc(date(2026, 10, 1), date(2026, 10, 1), settings)
    local_start = datetime(2026, 10, 1, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    local_end = datetime(2026, 10, 2, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    assert start == local_start
    assert end == local_end
