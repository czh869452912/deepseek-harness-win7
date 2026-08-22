from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.context.time_context.request_zone import (
    derive_browser_time_zone_context,
    render_browser_time_zone_context,
)
from dsh.context.time_context.timestamp import format_duration, format_timestamp

name = "time-context"


class TimeContextPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-time-context`: Injects request timestamp, local timezone,
    and elapsed time context into turn pre-step user messages.
    """

    id = "time-context"
    name = "@deepseek-ai/dsh-time-context"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.time_zone: Optional[str] = cfg.get("timeZone")
        self.refresh_interval_ms: int = int(cfg.get("refreshIntervalMs", 0))
        self._last_injection_time: Dict[str, float] = {}

    def apply(self, ctx: Any) -> None:
        async def hook_time_context(payload: Dict[str, Any]) -> Dict[str, Any]:
            messages = payload.get("messages", [])
            if not messages:
                return payload

            now = time.time()
            session_id = payload.get("session_id", "default")
            turn = payload.get("turn", 1)
            step = payload.get("step", 1)

            last_time = self._last_injection_time.get(session_id, 0)
            if self.refresh_interval_ms > 0 and last_time > 0:
                if (now - last_time) * 1000.0 < self.refresh_interval_ms:
                    return payload

            self._last_injection_time[session_id] = now

            formatted_time = format_timestamp(now * 1000.0, self.time_zone)
            dt_utc = datetime.fromtimestamp(now, tz=timezone.utc)
            utc_str = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

            zone_ctx = derive_browser_time_zone_context(messages)
            zone_text = render_browser_time_zone_context(zone_ctx)

            elapsed_str = format_duration((now - last_time) * 1000.0) if last_time > 0 else "unavailable"
            baseline = "model-visible message" if step == 1 else "step context"

            time_text = (
                f"[Context Time: {formatted_time} (UTC: {utc_str}) | {zone_text} | Elapsed since preceding {baseline}: {elapsed_str}]"
            )

            for msg in reversed(messages):
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    if "[Context Time:" not in msg["content"]:
                        msg["content"] = f"{time_text}\n{msg['content']}"
                    break

            return payload

        ctx.on("agent/pre-step", hook_time_context)


__all__ = [
    "TimeContextPlugin",
    "derive_browser_time_zone_context",
    "render_browser_time_zone_context",
    "format_timestamp",
    "format_duration",
    "name",
]
