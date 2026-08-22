import json
from typing import Any, Dict, List, Optional, Union


def derive_browser_time_zone_context(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    zones: List[str] = []
    for msg in messages:
        source = msg.get("source", {}) if isinstance(msg.get("source"), dict) else {}
        tz = source.get("clientTimeZone") or msg.get("clientTimeZone") or msg.get("timeZone") or msg.get("tz")
        if tz and isinstance(tz, str):
            if tz not in zones:
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
