from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin


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
        self.time_zone = cfg.get("timeZone")
        self.refresh_interval_ms = int(cfg.get("refreshIntervalMs", 0))
        self._last_injection_time: Dict[str, float] = {}

    def apply(self, ctx: Any) -> None:
        async def hook_time_context(payload: Dict[str, Any]) -> Dict[str, Any]:
            messages = payload.get("messages", [])
            if not messages:
                return payload

            now = time.time()
            session_id = payload.get("session_id", "default")
            last_time = self._last_injection_time.get(session_id, 0)
            if self.refresh_interval_ms > 0 and (now - last_time) * 1000 < self.refresh_interval_ms:
                return payload

            self._last_injection_time[session_id] = now

            local_dt = datetime.now()
            utc_dt = datetime.now(timezone.utc)
            tz_str = time.tzname[time.daylight] if time.daylight else time.tzname[0]
            iso_local = local_dt.strftime("%Y-%m-%dT%H:%M:%S")

            time_text = (
                f"[Context Time: {iso_local} (Local: {tz_str}, UTC: {utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})]"
            )

            # Inject into the last user message or system message
            for msg in reversed(messages):
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    if "[Context Time:" not in msg["content"]:
                        msg["content"] = f"{time_text}\n{msg['content']}"
                    break

            return payload

        ctx.on("agent/pre-step", hook_time_context)
