"""Provider error facts shared by HTTP and in-band stream failures."""
import re


def is_context_window_exceeded(detail):
    return any(re.search(pattern, detail, re.I) for pattern in (
        r"(?:^|[^a-z0-9])context[\s_-](?:length|window)[\s_-](?:exceed(?:ed|s)?|overflow(?:ed)?|limit[\s_-]exceeded)(?:$|[^a-z0-9])",
        r"\b(?:maximum|max)(?:\s+(?:allowed|supported))?\s+context\s+(?:length|window)\b",
        r"\b(?:request|prompt|input|messages?)\s+(?:is\s+|are\s+)?too\s+(?:large|long)\s+for\s+(?:(?:this|the)\s+)?(?:model(?:'s)?\s+)?context(?:\s+window)?\b",
        r"\b(?:input|prompt|request)\s+(?:is\s+)?too\s+(?:long|large)\s+for\s+(?:this|the)\s+model\b",
        r"\b(?:input|prompt|request|messages?)\b.{0,40}\b(?:exceed(?:s|ed)?|overflows?|is\s+larger\s+than)\b.{0,40}\b(?:the\s+)?(?:model(?:'s)?\s+)?context(?:\s+(?:length|window))?\b",
    ))


def is_quota_exceeded(detail):
    return any(re.search(pattern, detail, re.I) for pattern in (
        r"\binsufficient[\s_-]+(?:quota|balance|credits?)\b",
        r"\b(?:quota|usage[\s_-]+limit)[\s_-]+(?:exceeded|exhausted|reached)\b",
        r"\bexceed(?:ed|s)?[\s_-]+(?:(?:your|the)[\s_-]+)?(?:current[\s_-]+)?quota\b",
        r"\b(?:balance|credits?)[\s_-]+(?:exhausted|depleted)\b",
        r"\bout[\s_-]+of[\s_-]+(?:credits?|budget)\b",
    ))


def http_error_code(status, error=None):
    if status in (401, 403):
        return "AUTH"
    if status == 413:
        return "INVALID_REQUEST"
    fields = error if isinstance(error, dict) else {}
    detail = " ".join(fields[key] for key in ("code", "type", "message") if isinstance(fields.get(key), str))
    if is_quota_exceeded(detail):
        return "QUOTA_EXCEEDED"
    if status == 429:
        return "RATE_LIMIT"
    if status == 400:
        return "CONTEXT_WINDOW_EXCEEDED" if is_context_window_exceeded(detail) else "INVALID_REQUEST"
    return "SERVER" if status >= 500 else "HTTP_{}".format(status)
