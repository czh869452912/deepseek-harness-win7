"""
Cordis Logger Service matching reference/vendor/cordis/src/logger.ts
Implements Logger, LoggerService, Exporters, ANSI color hashing, and formatting.
"""

import json
import math
import re
import sys
import time
import traceback
import weakref
from typing import Any, Callable, Dict, List, Optional, Union

# ANSI color palette indexes used for logger name coloring matching TS Cordis
c16 = [6, 2, 3, 4, 5, 1]
c256 = [
    20, 21, 26, 27, 32, 33, 38, 39, 40, 41, 42, 43, 44, 45, 56, 57, 62,
    63, 68, 69, 74, 75, 76, 77, 78, 79, 80, 81, 92, 93, 98, 99, 112, 113,
    129, 134, 135, 148, 149, 160, 161, 162, 163, 164, 165, 166, 167, 168,
    169, 170, 171, 172, 173, 178, 179, 184, 185, 196, 197, 198, 199, 200,
    201, 202, 203, 204, 205, 206, 207, 208, 209, 214, 215, 220, 221,
]


class LoggerLevel:
    ERROR = 0
    INFO = 1
    WARN = 2
    DEBUG = 3


class Message:
    """Structured log record delivered to exporters."""
    def __init__(
        self,
        sn: int,
        ts: int,
        name: str,
        msg_type: Optional[str] = None,
        level: int = LoggerLevel.INFO,
        args: Optional[List[Any]] = None,
        fiber: Optional[Any] = None,
        meta: Optional[Dict[str, Any]] = None,
        type: Optional[str] = None,
    ):
        self.sn = sn
        self.ts = ts
        self.name = name
        self.type = type or msg_type or "info"
        self.level = level
        self.args = args if args is not None else []
        self.fiber = weakref.ref(fiber) if fiber is not None else None
        self.meta = meta or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sn": self.sn,
            "ts": self.ts,
            "name": self.name,
            "type": self.type,
            "level": self.level,
            "args": [str(a) if isinstance(a, Exception) else a for a in self.args],
            "meta": self.meta,
        }


class Exporter:
    """Sink that receives structured log messages."""
    def __init__(
        self,
        export_fn: Optional[Callable[[Message], None]] = None,
        colors: int = 3,
        max_length: int = 10240,
        levels: Optional[Dict[str, int]] = None,
        formatters: Optional[Dict[str, Callable[..., Any]]] = None,
    ):
        self._export_fn = export_fn
        self.colors = colors
        self.max_length = max_length
        self.levels = levels or {}
        self.formatters = formatters or {}

    def export(self, message: Message) -> None:
        if self._export_fn:
            self._export_fn(message)


def default_color(exporter: Exporter, code: int, value: Any, decoration: str = "") -> str:
    if not exporter.colors:
        return str(value)
    deco = decoration if exporter.colors >= 2 else ""
    if code < 8:
        return f"\033[3{code}{deco}m{value}\033[0m"
    return f"\033[38;5;{code}{deco}m{value}\033[0m"


def default_code(name: str, level: Optional[int] = 3) -> int:
    h = 0
    for ch in name:
        h = (((h << 3) - h) + ord(ch) + 13) & 0xFFFFFFFF
    signed_h = h if h < 0x80000000 else h - 0x100000000
    if not level:
        colors = []
    elif level >= 2:
        colors = c256
    else:
        colors = c16
    if not colors:
        return 0
    return colors[abs(signed_h) % len(colors)]


class Logger:
    """Logger facade for one named subsystem matching TS Logger."""

    c16 = c16
    c256 = c256
    color = staticmethod(default_color)
    code = staticmethod(default_code)

    def __init__(self, name: str, service: "LoggerService", level: Optional[int] = None, meta: Optional[Dict[str, Any]] = None):
        self.name = name
        self.service = service
        self.level = level if level is not None else LoggerLevel.INFO
        self.meta = meta or {}

    @classmethod
    def format(cls, exporter: Exporter, message: Message) -> str:
        args = list(message.args)
        if not args:
            return ""

        if isinstance(args[0], Exception):
            err = args[0]
            tb_str = "".join(traceback.format_exception(type(err), err, err.__traceback__)) if getattr(err, "__traceback__", None) else str(err)
            args[0] = tb_str
            args.insert(0, "%s")
        elif not isinstance(args[0], str):
            args.insert(0, "%o")

        fmt_str = str(args.pop(0))

        def replace_placeholder(match: re.Match) -> str:
            ch = match.group(1)
            if ch == "%":
                return "%"
            if ch not in exporter.formatters and ch not in ("s", "d", "i", "f", "o", "O", "c", "C"):
                return match.group(0)

            val = args.pop(0) if args else None
            if ch in exporter.formatters:
                return str(exporter.formatters[ch](val, exporter, message))
            if ch == "s":
                return "undefined" if val is None else str(val)
            if ch in ("d", "i"):
                try:
                    f_val = float(val)
                    if math.isnan(f_val):
                        return "NaN"
                    return str(int(math.trunc(f_val)))
                except (ValueError, TypeError):
                    return "NaN"
            if ch == "f":
                try:
                    f_val = float(val)
                    if math.isnan(f_val):
                        return "NaN"
                    return str(f_val)
                except (ValueError, TypeError):
                    return "NaN"
            if ch in ("o", "O"):
                try:
                    return json.dumps(val, default=str, ensure_ascii=False)
                except Exception:
                    return str(val)
            if ch == "c":
                return ""
            if ch == "C":
                c_val = Logger.code(message.name, exporter.colors)
                return Logger.color(exporter, c_val, str(val))
            return str(val)

        res = re.sub(r"%([a-zA-Z%])", replace_placeholder, fmt_str)

        o_formatter = exporter.formatters.get("o") if exporter.formatters else None
        for remaining in args:
            if o_formatter is not None and not isinstance(remaining, (str, int, float, bool)):
                res += " " + str(o_formatter(remaining, exporter, message))
            elif isinstance(remaining, (dict, list)):
                try:
                    res += " " + json.dumps(remaining, default=str, ensure_ascii=False)
                except Exception:
                    res += f" {remaining}"
            else:
                res += f" {remaining}"

        max_len = exporter.max_length
        lines = []
        for line in res.splitlines():
            if len(line) > max_len:
                lines.append(line[:max_len] + "...")
            else:
                lines.append(line)
        return "\n".join(lines)

    def _method(self, msg_type: str, level: int, format_str: Any, *args: Any) -> None:
        if not args and isinstance(format_str, Exception):
            err = format_str
            if getattr(err, "__cause__", None) is not None:
                getattr(self, msg_type)(err.__cause__)
            elif hasattr(err, "errors") and isinstance(getattr(err, "errors"), (list, tuple)) and err.errors:
                for sub_err in err.errors:
                    getattr(self, msg_type)(sub_err)
                return

        all_args = [format_str] + list(args) if format_str is not None else list(args)
        sn = self.service._next_message_sn()
        ts = int(time.time() * 1000)
        fiber = self.meta.get("fiber")
        if fiber and isinstance(fiber, weakref.ReferenceType):
            fiber = fiber()

        message = Message(
            sn=sn,
            ts=ts,
            name=self.name,
            msg_type=msg_type,
            level=level,
            args=all_args,
            fiber=fiber,
            meta=self.meta
        )

        for exporter in list(self.service.exporters.values()):
            target_level = exporter.levels.get(self.name, exporter.levels.get("default", self.level))
            if target_level < level:
                continue
            exporter.export(message)

    def error(self, format_str: Any, *args: Any) -> None:
        self._method("error", LoggerLevel.ERROR, format_str, *args)

    def info(self, format_str: Any, *args: Any) -> None:
        self._method("info", LoggerLevel.INFO, format_str, *args)

    def warn(self, format_str: Any, *args: Any) -> None:
        self._method("warn", LoggerLevel.WARN, format_str, *args)

    def debug(self, format_str: Any, *args: Any) -> None:
        self._method("debug", LoggerLevel.DEBUG, format_str, *args)


class LoggerService:
    """
    Built-in Cordis logging service matching reference/vendor/cordis/src/logger.ts.
    Registered as ctx.logger.
    """

    name = "logger"

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.buffer_size = 1000
        self.buffer: List[Message] = []
        self._sn_message = 0
        self._sn_exporter = 0
        self.exporters: Dict[int, Exporter] = {}

        # Default internal exporter writing to memory ring buffer
        def record_buffer(msg: Message) -> None:
            self.buffer.append(msg)
            if len(self.buffer) > self.buffer_size:
                self.buffer = self.buffer[-self.buffer_size:]

        self.exporter(Exporter(export_fn=record_buffer, colors=3))

    def _next_message_sn(self) -> int:
        self._sn_message += 1
        return self._sn_message

    def exporter(self, exporter: Exporter) -> Callable[[], None]:
        """
        Register an exporter and dispose it with the current fiber effect.
        """
        def setup() -> Callable[[], None]:
            self._sn_exporter += 1
            sn = self._sn_exporter
            self.exporters[sn] = exporter

            def teardown() -> None:
                # Upstream TS quirk: deletes the current _sn_exporter
                self.exporters.pop(self._sn_exporter, None)

            return teardown

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(setup, label="ctx.logger.exporter()")
        return setup()

    def __call__(self, name: Optional[str] = None) -> Logger:
        """Create or get a named Logger instance."""
        from dsh.cordis.utils import hyphenate
        config = self.resolve_intercept_config() or {} if hasattr(self, "resolve_intercept_config") else {}
        target_name = name or config.get("name")
        fiber = getattr(self.ctx, "fiber", None)
        if not target_name:
            fname = getattr(fiber, "name", "root") if fiber else "root"
            target_name = hyphenate(fname) if fname else "root"
        level = config.get("level", LoggerLevel.INFO)
        return Logger(name=target_name, service=self, level=level, meta={"fiber": fiber})

    def error(self, format_str: Any, *args: Any) -> None:
        self().error(format_str, *args)

    def info(self, format_str: Any, *args: Any) -> None:
        self().info(format_str, *args)

    def warn(self, format_str: Any, *args: Any) -> None:
        self().warn(format_str, *args)

    def debug(self, format_str: Any, *args: Any) -> None:
        self().debug(format_str, *args)
