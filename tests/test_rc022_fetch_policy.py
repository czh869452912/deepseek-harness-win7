import hashlib
import json

import pytest

from dsh.web.fetch_policy_current import decoderForCharset
from scripts.rc022_fetch_policy_probe import observe


@pytest.mark.asyncio
async def test_fixed_source_policy_and_decoder_corpus():
    # Canonical digest of the unchanged 38a6a5c Source/Node v24.9.0 oracle,
    # qualified by rc022-fetch-policy-paired6 (URLs, MIME, all labels and bytes,
    # seeded multibyte inputs, GB18030 boundaries and ISO escape/chunk recovery).
    rows = await observe()
    assert len(rows) == 2641
    encoded = json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert hashlib.sha256(encoded).hexdigest() == 'cd2fc2841abfdc871a60605876592340edf1cec7a852bbe33cbccaa08fe9a0aa'


def test_decoder_stream_reset_bom_and_fatal_recovery():
    decoder = decoderForCharset('utf-8,gbk')
    assert decoder.decode(b'\xef', stream=True) == ''
    assert decoder.decode(b'\xbb\xbfA', stream=True) == 'A'
    assert decoder.decode(b'\xef\xbb\xbf') == '\ufeff'
    assert decoder.decode(b'\xef\xbb\xbfB') == 'B'
    assert decoder.decode(b'\xe4', stream=True) == ''
    with pytest.raises(UnicodeError): decoder.decode(b'X', stream=True)
    assert decoder.decode(b'\xef\xbb\xbfC') == 'C'
    assert decoder.decode(b'\xe4', stream=True) == ''
    with pytest.raises(UnicodeError): decoder.decode(b'')
    assert decoder.decode(b'D') == 'D'


def test_iso_escape_state_resets_and_pinned_stream_overflow():
    decoder = decoderForCharset('iso-2022-jp')
    assert decoder.decode(b'\x1b$B\x24', stream=True) == ''
    assert decoder.decode(b'\x22') == '\u3042'
    assert decoder.decode(b'\x24\x22') == '$"'
    assert decoder.decode(b'\x1b(', stream=True) == ''
    with pytest.raises(UnicodeError): decoder.decode(b'X', stream=True)
    assert decoder.decode(b'\\~') == '\\~'
