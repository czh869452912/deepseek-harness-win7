import asyncio
import gzip
import json
import threading
import zlib

import pytest

from dsh.host.http_decode import decompressChunks
from scripts import rc022_account_protocol_probe as corpus


@pytest.mark.asyncio
async def test_actual_platform_http_policies_envelopes_and_owned_teardown(tmp_path):
    before = {thread.ident for thread in threading.enumerate()}
    rows = await corpus.observe()
    (tmp_path/'account-protocol-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == len(corpus.cases())
    logs = json.dumps([row['diagnostics'] for row in rows])
    for secret in ('request-secret', 'response-secret', 'fixture-token', 'private-'):
        assert secret not in logs
    http = [(case, row) for case, row in zip(corpus.cases(), rows) if case['kind'] == 'http']
    assert all(row['result']['error']['unauthorized'] for case, row in http
               if case.get('status') == 401 and case['op'] == 'account')
    assert all(row['diagnostics'] == [] for case, row in http
               if case.get('mode') in ('pre-abort', 'header-abort', 'body-abort'))
    assert all(row['diagnostics'] for case, row in http if 'timeout' in case.get('mode', ''))
    bomb = next(row for case, row in http if case.get('wire') == 'gzip-bomb')
    assert bomb['result']['error']['code'] == 'protocol'
    assert bomb['diagnostics'][0]['stage'] == 'body-limit'
    assert not any('/leaked' in hit['path'] for row in rows for hit in row['hits'])
    for _ in range(100):
        active = [thread for thread in threading.enumerate() if thread.ident not in before and
                  thread.name in ('dsh-model-reader', 'dsh-http-cancellation', 'account-protocol-probe')]
        if not active:
            break
        await asyncio.sleep(.002)
    assert not active


@pytest.mark.parametrize('encoding', ['gzip', 'deflate', 'raw-deflate'])
def test_compressed_expansion_is_bounded_before_consumer_body_limit(encoding):
    payload = b'x'*(1024*1024)
    if encoding == 'gzip':
        compressed = gzip.compress(payload[:len(payload)//2])+gzip.compress(payload[len(payload)//2:])
    elif encoding == 'deflate':
        compressed = zlib.compress(payload)
    else:
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(payload)+compressor.flush()
    chunks = list(decompressChunks([compressed[:1], compressed[1:]], 'deflate' if encoding == 'raw-deflate' else encoding))
    assert max(map(len, chunks)) <= 65536
    assert b''.join(chunks) == payload
