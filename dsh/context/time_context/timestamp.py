from datetime import datetime, timezone
import math
import time
from typing import Optional

try:
    import zoneinfo
except ImportError:
    zoneinfo = None  # Python < 3.9 fallback if needed


def format_duration(elapsed_ms: float) -> str:
    seconds = math.floor(max(0.0, elapsed_ms) / 1000.0)
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def format_timestamp(timestamp_ms: Optional[float] = None, tz_name: Optional[str] = None) -> str:
    ts = (timestamp_ms / 1000.0) if timestamp_ms is not None else time.time()
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    # Try resolving zoneinfo if timezone name is provided
    tz = None
    if tz_name and zoneinfo is not None:
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = None

    if tz is not None:
        local_dt = dt.astimezone(tz)
        label = tz_name
    else:
        local_dt = datetime.fromtimestamp(ts).astimezone()
        label = tz_name or (time.tzname[time.daylight] if time.daylight else time.tzname[0])

    offset_str = local_dt.strftime("%z")
    if offset_str and len(offset_str) == 5:
        offset_formatted = f"{offset_str[:3]}:{offset_str[3:]}"
    else:
        offset_formatted = "+00:00"

    iso_str = local_dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{iso_str}{offset_formatted}[{label}]"
