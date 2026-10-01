"""Shared Python 3.8 representation of JavaScript aggregate exceptions."""
from typing import Any, Dict, Iterable, Optional

_ABSENT = object()


class ThrownValueError(RuntimeError):
    """Python carrier for a JS thrown value that is not a BaseException."""
    def __init__(self, value: Any, message: str = "operation aborted"):
        super().__init__(message)
        self.value = value
        self.reason = value


class AggregateError(RuntimeError):
    def __init__(self, errors: Iterable[Any], message: str = "",
                 options: Optional[Dict[str, Any]] = None, *, cause: Any = _ABSENT):
        super().__init__(message)
        self.message = message
        self.name = "AggregateError"
        self.errors = list(errors)
        if cause is not _ABSENT:
            self.cause = cause
        elif options is not None and "cause" in options:
            self.cause = options["cause"]


def safe_string(value: Any) -> str:
    """Contain legacy Python presentation without discarding aggregate members."""
    try:
        return str(value)
    except BaseException:
        return "<unrenderable value>"
