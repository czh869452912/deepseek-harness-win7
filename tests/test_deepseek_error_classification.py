import pytest

from dsh.llm.provider_errors import http_error_code


@pytest.mark.parametrize("status,detail,expected", [
    (401, {"message": "insufficient quota"}, "AUTH"),
    (413, {"message": "maximum context length"}, "INVALID_REQUEST"),
    (429, {"code": "insufficient_quota"}, "QUOTA"),
    (429, {"message": "quota reset in one minute"}, "RATE_LIMIT"),
    (402, {"message": "balance depleted"}, "QUOTA"),
    (500, {"type": "usage_limit_reached"}, "QUOTA"),
    (400, {"code": "context_length_exceeded"}, "CONTEXT_WINDOW_EXCEEDED"),
    (400, {"message": "prompt too long for this model"}, "CONTEXT_WINDOW_EXCEEDED"),
    (400, {"message": "missing context field"}, "INVALID_REQUEST"),
    (500, {}, "SERVER"), (404, {}, "HTTP_404"),
])
def test_error_facts_distinguish_terminal_quota_from_retryable_rate_limit(status, detail, expected):
    assert http_error_code(status, detail) == expected
