import json
import re
from typing import Any, Dict, List, Optional

IANA_TIME_ZONE_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9_+.-]*(?:\/[A-Za-z0-9_+.-]+)+$")


def browser_time_zone(message: Dict[str, Any]) -> Optional[str]:
    source = message.get("source")
    value = None
    if isinstance(source, dict) and source.get("kind") == "user" and "rpcId" in source and isinstance(source.get("clientTimeZone"), str):
        value = source["clientTimeZone"]
    elif isinstance(message, dict):
        value = message.get("clientTimeZone") or message.get("timeZone") or message.get("tz")
        if isinstance(source, dict) and not value:
            value = source.get("clientTimeZone") or source.get("timeZone") or source.get("tz")

    if value is None or not isinstance(value, str):
        return None

    if value != "UTC" and not IANA_TIME_ZONE_REGEX.match(value):
        raise TypeError(
            f"browser time zone must be canonical UTC or IANA Area/Location: {json.dumps(value)}"
        )

    try:
        from zoneinfo import ZoneInfo
        zi = ZoneInfo(value)
        canonical = zi.key
    except Exception as e:
        raise TypeError(f"browser time zone is unsupported: {json.dumps(value)}") from e

    if canonical != value:
        raise TypeError(f"browser time zone must be canonical: {json.dumps(value)}")

    return value


def derive_browser_time_zone_context(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    zones: List[str] = []
    for msg in messages:
        tz = browser_time_zone(msg)
        if tz is not None and tz not in zones:
            zones.append(tz)

    zones.sort()
    if not zones:
        return {"kind": "missing"}
    if len(zones) == 1:
        return {"kind": "resolved", "timeZone": zones[0]}
    return {"kind": "mixed", "timeZones": zones}


def render_browser_time_zone_context(context: Dict[str, Any]) -> str:
    kind = context.get("kind")
    if kind == "resolved":
        return (
            f"Browser time zone for this request: {context['timeZone']}. "
            "Interpret otherwise-unqualified dates and times in this zone."
        )
    if kind == "mixed":
        return (
            f"Browser time zone for this request: mixed {json.dumps(context['timeZones'])}. "
            "Ask the user to clarify otherwise-unqualified dates and times."
        )
    return (
        "Browser time zone for this request: unavailable. "
        "Ask the user to clarify otherwise-unqualified dates and times."
    )
