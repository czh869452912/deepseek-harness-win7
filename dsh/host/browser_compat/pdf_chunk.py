"""Build-owned syntax adaptation for the pinned PDF.js lazy client."""
import hashlib
import json
from pathlib import Path

PACKAGE = '@deepseek-ai/dsh-client-ui-sidebar-documentpreview'
CHUNK = 'client.pdf.js'
_RULE = json.loads(Path(__file__).with_name('pdf-regexp.json').read_text(encoding='utf-8'))
_ORIGINAL = _RULE['original'].encode('utf-8')
_REPLACEMENT = _RULE['replacement'].encode('utf-8')
REVISION = hashlib.sha256(_REPLACEMENT).hexdigest()


def adapt_pdf_chunk(bundle):
    normalized = bundle.replace(b'\r\n', b'\n')
    if hashlib.sha256(normalized).hexdigest() != _RULE['sourceSha256']:
        return bundle
    if bundle.count(_ORIGINAL) != 1:
        raise ValueError('Pinned PDF.js auto-link regular expression is missing or ambiguous')
    return bundle.replace(_ORIGINAL, _REPLACEMENT)
