"""Issue #12 compatibility checks for the pinned PDF and custom error DTOs."""
from pathlib import Path

import pytest

from dsh.host.browser_compat.pdf_chunk import adapt_pdf_chunk
from dsh.llm.pi_stream import stop_reason


def test_transpile_pinned_pdf_link_pattern_without_rewriting_unknown_bundles():
    root = Path(__file__).resolve().parents[1]
    pinned = (root / 'packages/client/ui-sidebar-documentpreview/lib/client.pdf.js').read_bytes()
    adapted = adapt_pdf_chunk(pinned)
    assert adapted != pinned
    assert b'findLinks(text){this.#regex??=' in adapted
    assert adapted.count(b'__ModuleLoader__.load') == pinned.count(b'__ModuleLoader__.load')
    assert adapt_pdf_chunk(pinned + b' ') == pinned + b' '


@pytest.mark.parametrize(('message', 'code'), [
    ('413 {"error":{"code":"context_limit_exceeded","message":"input is too large"}}', 'CONTEXT_WINDOW_EXCEEDED'),
    ('422 {"error":{"type":"context_length_error","message":"input is too large"}}', 'CONTEXT_WINDOW_EXCEEDED'),
    ('413 {"error":{"code":"payload_too_large"}}', 'INVALID_REQUEST'),
    ('413 (no body)', 'INVALID_REQUEST'),
    ('429 {"error":{"code":"context_length_exceeded","message":"rate limit"}}', 'RATE_LIMIT'),
    ('400 {"error":{"code":"E_INPUT_BUDGET","message":"input is too large"}}', 'INVALID_REQUEST'),
])
def test_pi_adapter_distinguishes_reported_context_limit_from_generic_size(message, code):
    response = dict(stopReason='error', errorMessage=message, usage=dict(input=0, cacheRead=0))
    assert stop_reason(response)['failure']['code'] == code
