from datetime import datetime, timezone
import time
from typing import Optional


def format_timestamp(timestamp_ms: Optional[float] = None, tz_name: Optional[str] = None) -> str:
    ts = timestamp_ms / 1000.0 if timestamp_ms else time.time()
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    local_dt = datetime.fromtimestamp(ts)
    tz_str = tz_name or (time.tzname[time.daylight] if time.daylight else time.tzname[0])
    return f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz_str}, UTC: {dt.strftime('%Y-%m-%dT%H:%M:%SZ')})"
