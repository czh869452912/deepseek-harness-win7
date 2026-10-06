import inspect
import math

from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.llm.error import HarnessError


def normalize_llm_failure(error):
    from dsh.llm.llm_service import LlmError
    if isinstance(error, ThrownValueError):
        try:
            message = js_to_string(error.value) if error.value is None or type(error.value) in (str, bool, int, float) else str(error.value)
        except Exception:
            message = 'LLM adapter failed'
        return dict(message=message or 'LLM adapter failed', code='UNKNOWN')
    try:
        attributes = object.__getattribute__(error, '__dict__')
        carried = attributes.get('failure')
        own_code = attributes.get('code')
    except Exception:
        carried, own_code = None, None
    try:
        if isinstance(carried, dict):
            message, code = carried.get('message'), carried.get('code')
            status, delay, request_id = carried.get('status'), carried.get('providerRetryAfterMs'), carried.get('requestId')
            valid = isinstance(message, str) and bool(message) and isinstance(code, str) and bool(code)
            valid = valid and ('status' not in carried or type(status) in (int, float) and math.isfinite(status) and status == math.floor(status) and 100 <= status <= 599)
            valid = valid and ('providerRetryAfterMs' not in carried or type(delay) in (int, float) and math.isfinite(delay) and delay > 0)
            valid = valid and ('requestId' not in carried or isinstance(request_id, str) and bool(request_id))
            if valid and code == own_code:
                return dict(message=message, code=code, **{key: value for key, value in (
                    ('status', status), ('providerRetryAfterMs', delay), ('requestId', request_id)) if value is not None})
    except Exception:
        pass
    try:
        sentinel = object()
        message = str(error) if inspect.getattr_static(error, 'message', sentinel) is sentinel else error.message
        if not isinstance(message, str) or not message:
            message = 'LLM adapter failed'
    except Exception:
        message = 'LLM adapter failed'
    return dict(message=message, code=error.code if isinstance(error, (HarnessError, LlmError)) else 'UNKNOWN')
