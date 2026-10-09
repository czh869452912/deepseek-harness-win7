"""
HarnessError base exception class matching @deepseek-ai/dsh-llm
"""
import inspect
from typing import Any, Dict, Optional, Set

from dsh.cordis.utils import _UNDEFINED, js_to_string
from dsh.cordis.errors import AggregateError, ThrownValueError

_MISSING = object()


class HarnessError(Exception):
    """
    Base exception class for Harness errors with error message and code.
    """

    def __init__(self, message: str, code: str = "HARNESS_ERROR",
                 options: Optional[Dict[str, Any]] = None, *, cause: Any = _UNDEFINED):
        super().__init__(message)
        self.message = message
        self.code = code
        self.name = self.__class__.__name__
        if cause is not _UNDEFINED:
            self.cause = cause
        elif options is not None and "cause" in options:
            self.cause = options["cause"]

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def _own_message(value: Any) -> Any:
    # Like getOwnPropertyDescriptor: a plain object's property getter is never
    # invoked just to obtain a diagnostic. Exception properties are different
    # and are read normally in error_chain, as the source reads Error.message.
    if isinstance(value, dict):
        return dict.get(value, "message", _UNDEFINED)
    try:
        attributes = object.__getattribute__(value, "__dict__")
    except AttributeError:
        return _UNDEFINED
    return attributes.get("message", _UNDEFINED)


def _primitive(value: Any) -> bool:
    return value is None or value is _UNDEFINED or isinstance(value, (str, bool, int, float))


def _error_attribute(value: BaseException, name: str, default: Any) -> Any:
    if inspect.getattr_static(value, name, _MISSING) is not _MISSING:
        # A getter throwing AttributeError is hostile, not an absent property.
        return getattr(value, name)
    return getattr(value, name, default)


def _message(value: BaseException) -> Any:
    message = _error_attribute(value, "message", _MISSING)
    return str(value) if message is _MISSING else message


def _cause(value: BaseException) -> Any:
    cause = _error_attribute(value, "cause", _MISSING)
    return value.__cause__ if cause is _MISSING else cause


def _string(value: Any, arrays: Optional[Set[int]] = None) -> str:
    if _primitive(value):
        return js_to_string(value)
    if isinstance(value, BaseException):
        message = _message(value)
        name = _error_attribute(value, "name", type(value).__name__)
        text = _string(message)
        return _string(name) + (": " + text if text else "")
    if isinstance(value, (list, tuple)):
        if arrays is None:
            arrays = set()
        if id(value) in arrays:
            return ""
        arrays.add(id(value))
        try:
            return ",".join("" if item is None or item is _UNDEFINED else _string(item, arrays) for item in value)
        finally:
            arrays.remove(id(value))
    if isinstance(value, dict):
        to_string = dict.get(value, "toString", _UNDEFINED)
        value_of = dict.get(value, "valueOf", _UNDEFINED)
    else:
        to_string = _error_attribute(value, "toString", _UNDEFINED)
        value_of = _error_attribute(value, "valueOf", _UNDEFINED)
    if to_string is _UNDEFINED:
        if type(value).__str__ is not object.__str__ and not isinstance(value, dict):
            return str(value)
        return js_to_string(value)
    if callable(to_string):
        converted = to_string()
        if _primitive(converted):
            return _string(converted)
    if callable(value_of):
        converted = value_of()
        if _primitive(converted):
            return _string(converted)
    raise TypeError("Cannot convert object to primitive value")


def stringify_value(value: Any) -> str:
    """Convert a diagnostic value using JavaScript String semantics.

    Conversion failures remain visible to the caller so each public error
    boundary can apply its own Source-defined fallback.
    """
    return _string(value)


def error_chain(value: Any) -> str:
    """Render explicit causes and aggregate members without escaping failures.

    Port of dsh-llm/error.ts. Python's explicit ``raise ... from ...`` cause is
    used when no ``cause`` attribute exists; implicit __context__ is excluded.
    Identity is tracked only on the active path, so shared causes are not cycles.
    """
    path: Set[int] = set()

    def render(current: Any) -> str:
        identity = id(current)
        if identity in path:
            return "<circular cause>"
        path.add(identity)
        try:
            if isinstance(current, ThrownValueError):
                return render(current.value)
            if not isinstance(current, BaseException):
                message = _own_message(current) if not _primitive(current) else _UNDEFINED
                return message if isinstance(message, str) else _string(current)
            # Preserve the source's accessor reads and their order. A getter
            # may return once and throw on the second read.
            message = (_error_attribute(current, "name", type(current).__name__)
                       if _message(current) == "" else _message(current))
            members = ""
            if isinstance(current, AggregateError):
                if current.errors:
                    members = " [" + "; ".join(render(item) for item in current.errors) + "]"
            # A present .cause (even null/undefined) wins over __cause__.
            cause_text = "" if _cause(current) is _UNDEFINED or _cause(current) is None else render(_cause(current))
            suffix = "" if cause_text == "" or cause_text == message else ": " + cause_text
            return _string(message) + members + suffix
        except BaseException:
            return "<unrenderable value>"
        finally:
            path.remove(identity)

    return render(value)


errorChain = error_chain
