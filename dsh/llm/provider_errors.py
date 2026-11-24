"""Provider error facts shared by HTTP and in-band stream failures."""
import re
from dsh.host.http_proxy_policy import JS_SPACE


def _search(pattern, detail):
    # JS /i uses ASCII word boundaries and its own whitespace set.
    pattern = pattern.replace(r'[\s_-]','['+JS_SPACE+'_-]').replace(r'\s','['+JS_SPACE+']')
    return re.search(pattern,detail,re.I | re.ASCII)


def is_context_window_exceeded(detail):
    return any(_search(pattern, detail) for pattern in (
        r"(?:^|[^a-z0-9])context[\s_-](?:length|window)[\s_-](?:exceed(?:ed|s)?|overflow(?:ed)?|limit[\s_-]exceeded)(?:$|[^a-z0-9])",
        r"\b(?:maximum|max)(?:\s+(?:allowed|supported))?\s+context\s+(?:length|window)\b",
        r"\b(?:request|prompt|input|messages?)\s+(?:is\s+|are\s+)?too\s+(?:large|long)\s+for\s+(?:(?:this|the)\s+)?(?:model(?:'s)?\s+)?context(?:\s+window)?\b",
        r"\b(?:input|prompt|request)\s+(?:is\s+)?too\s+(?:long|large)\s+for\s+(?:this|the)\s+model\b",
        r"\b(?:input|prompt|request|messages?)\b.{0,40}\b(?:exceed(?:s|ed)?|overflows?|is\s+larger\s+than)\b.{0,40}\b(?:the\s+)?(?:model(?:'s)?\s+)?context(?:\s+(?:length|window))?\b",
    ))


def is_quota_exceeded(detail):
    return any(_search(pattern, detail) for pattern in (
        r"\binsufficient[\s_-]+(?:quota|balance|credits?)\b",
        r"\b(?:quota|usage[\s_-]+limit)[\s_-]+(?:exceeded|exhausted|reached)\b",
        r"\bexceed(?:ed|s)?[\s_-]+(?:(?:your|the)[\s_-]+)?(?:current[\s_-]+)?quota\b",
        r"\b(?:balance|credits?)[\s_-]+(?:exhausted|depleted)\b",
        r"\bout[\s_-]+of[\s_-]+(?:credits?|budget)\b",
    ))


CONTEXT_LIMIT_CODES = frozenset((
    "context_length_exceeded", "context_window_exceeded", "model_context_window_exceeded",
    "context_limit_exceeded", "context_length_error", "context_window_too_large",
))


def explicit_context_limit(error):
    return isinstance(error, dict) and any(
        isinstance(error.get(key), str) and error[key].lower() in CONTEXT_LIMIT_CODES
        for key in ("code", "type")
    )


def http_error_code(status, error=None):
    if status in (401, 403):
        return "AUTH"
    if status in (400, 413, 422) and explicit_context_limit(error):
        return "CONTEXT_WINDOW_EXCEEDED"
    if status == 413:
        return "INVALID_REQUEST"
    fields = error if isinstance(error, dict) else {}
    detail = " ".join(fields[key] for key in ("code", "type", "message") if isinstance(fields.get(key), str))
    if is_quota_exceeded(detail):
        return "QUOTA"
    if status == 429:
        return "RATE_LIMIT"
    if status == 400:
        return "CONTEXT_WINDOW_EXCEEDED" if is_context_window_exceeded(detail) else "INVALID_REQUEST"
    return "SERVER" if status >= 500 else "HTTP_{}".format(status)
