from typing import Any, Dict, List, Optional


def derive_browser_time_zone_context(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Extract timezone from user message metadata if available
    for msg in reversed(messages):
        tz = msg.get("timeZone") or msg.get("tz")
        if tz:
            return {"kind": "resolved", "timeZone": str(tz)}
    return {"kind": "process"}


def render_browser_time_zone_context(ctx: Dict[str, Any]) -> str:
    if ctx.get("kind") == "resolved":
        return f"Browser Time Zone: {ctx.get('timeZone')}"
    return "Browser Time Zone: system local"
