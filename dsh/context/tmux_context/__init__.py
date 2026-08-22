import json
import os
import subprocess
import time
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin

name = "tmux-context"


class TmuxContextPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tmux-context`: Injects tmux session/window/pane location
    into agent pre-step context when running inside a genuine tmux pane.
    """

    id = "tmux-context"
    name = "@deepseek-ai/dsh-tmux-context"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.refresh_interval_ms: int = int(cfg.get("refreshIntervalMs", 0))
        self._last_state: Dict[str, str] = {}
        self._last_time: Dict[str, float] = {}

    def query_tmux_location(self) -> Optional[Dict[str, str]]:
        tmux_pane = os.environ.get("TMUX_PANE")
        if not tmux_pane:
            return None

        if os.name == "posix":
            try:
                ps_res = subprocess.run(
                    ["ps", "-o", "tty=", "-p", str(os.getpid())],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                self_tty = ps_res.stdout.strip()
                if not self_tty:
                    return None

                pane_res = subprocess.run(
                    ["tmux", "display-message", "-t", tmux_pane, "-p", "#{pane_tty}"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                pane_tty = pane_res.stdout.strip()
                if pane_tty != f"/dev/{self_tty}":
                    return None
            except Exception:
                return None

        format_str = "\\t".join([
            "#{session_name}",
            "#{window_index}",
            "#{window_name}",
            "#{pane_index}",
            "#{pane_id}",
            "#{window_active}",
            "#{pane_active}",
            "#{window_layout}",
        ])
        cmd = ["tmux", "display-message", "-t", tmux_pane, "-p", format_str]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode != 0 or not res.stdout:
                return None
            out = res.stdout.strip()
            parts = out.split("\\t") if "\\t" in out else out.split("\t")
            if len(parts) != 8:
                return None
            return {
                "sessionName": parts[0],
                "windowIndex": parts[1],
                "windowName": parts[2],
                "paneIndex": parts[3],
                "paneId": parts[4],
                "windowActive": parts[5],
                "paneActive": parts[6],
                "windowLayout": parts[7],
            }
        except Exception:
            return None

    def render_state(self, loc: Dict[str, str]) -> str:
        return (
            f"session {loc['sessionName']}, window {loc['windowIndex']} {json.dumps(loc['windowName'])}, "
            f"pane {loc['paneIndex']} {loc['paneId']}\n"
            f"window active={loc['windowActive']}, pane active={loc['paneActive']}, "
            f"layout {loc['windowLayout']}"
        )

    def render_reading(self, loc: Dict[str, str], turn: int) -> str:
        return f"tmux location (turn {turn}):\n{self.render_state(loc)}"

    def apply(self, ctx: Any) -> None:
        async def hook_tmux_context(payload: Dict[str, Any]) -> Dict[str, Any]:
            messages = payload.get("messages", [])
            if not messages:
                return payload

            step = payload.get("step", 1)
            if step != 1:
                return payload

            session_id = payload.get("session_id", "default")
            turn = payload.get("turn", 1)
            now = time.time()

            last_t = self._last_time.get(session_id, 0)
            if self.refresh_interval_ms > 0 and last_t > 0:
                if (now - last_t) * 1000.0 < self.refresh_interval_ms:
                    return payload

            loc = self.query_tmux_location()
            if not loc:
                return payload

            state_str = self.render_state(loc)
            if self._last_state.get(session_id) == state_str:
                return payload

            self._last_state[session_id] = state_str
            self._last_time[session_id] = now

            reading_text = self.render_reading(loc, turn)
            for msg in reversed(messages):
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    msg["content"] = f"{reading_text}\n{msg['content']}"
                    break

            return payload

        ctx.on("agent/pre-step", hook_tmux_context)


__all__ = ["TmuxContextPlugin", "name"]
