import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from dsh.boot.market_detail_022 import MarketDetailReader
from dsh.core.abort import AbortController
from dsh.util.plugin_detail import DetailFailure
from scripts.rc022_market_detail_probe import observe


@pytest.mark.asyncio
async def test_detail_cache_and_image_observations():
    rows = await observe(); by = {row['step']: row for row in rows}
    assert len(rows) == 36
    assert by['shared']['same']
    assert by['shared']['value']['origin'] == 'locale'
    assert by['image:img/a.png?raw=1#x']['value'] == dict(bytes=[112, 110, 103], mediaType='image/png')
    assert by['image:../../escape.png']['value'] is None
    assert by['image:big.gif']['error']['reason'] == 'too-large'
    assert by['expired-id']['value'] is None
    assert by['exact-ttl-image']['value'] is not None
    for reason in ['too-large', 'denied', 'invalid']:
        assert by['failure-reads:'+reason]['reads'] == 1
    for reason in ['network', 'git-unavailable']:
        assert by['failure-reads:'+reason]['reads'] == 2
    assert by['settled']['pending'] == 0


def reader(repository_files=None, manifest_repository=None, clock=None):
    signal = AbortController().signal
    return MarketDetailReader(dict(maxDocumentBytes=100, maxImageBytes=10, ttlMs=1000),
        dict(lifetime=signal), repository_files, manifest_repository, clock)


@pytest.mark.asyncio
async def test_cancelled_reader_leaves_shared_selection_live():
    gate = asyncio.get_running_loop().create_future(); entered = asyncio.Event(); calls = []
    async def read(*_): return None
    async def readme(*_): calls.append(1); entered.set(); return await gate
    files = SimpleNamespace(key='shared', read=read, readme=readme)
    details = reader(); location = dict(files=files, dir='')
    one = asyncio.create_task(details.read(location, ['en'])); two = asyncio.create_task(details.read(location, ['en']))
    await entered.wait(); one.cancel()
    with pytest.raises(asyncio.CancelledError): await one
    assert len(details.pending) == 1
    gate.set_result(dict(path='README.md', bytes=b'# Shared'))
    result = await two
    assert result['markdown'] == '# Shared' and calls == [1]
    assert not details.pending


@pytest.mark.asyncio
async def test_expiring_lasting_failure_can_be_retried_with_refresh():
    count = []; now = [0]
    async def read(*_): count.append(1); raise DetailFailure('denied', 'private')
    files = SimpleNamespace(key='denied', read=read); details = reader(clock=lambda: now[0]); location = dict(files=files, dir='')
    for _ in range(2):
        with pytest.raises(DetailFailure): await details.read(location, ['en'])
    assert len(count) == 1
    with pytest.raises(DetailFailure): await details.read(location, ['en'], True)
    assert len(count) == 2
    now[0] = 1000
    with pytest.raises(DetailFailure): await details.read(location, ['en'])
    assert len(count) == 3


@pytest.mark.asyncio
async def test_repository_fallback_receives_default_branch_and_directory():
    calls = []; repository = dict(url='https://github.com/o/r.git', directory='packages/a')
    async def read(path, *args):
        return json.dumps(dict(repository=repository)).encode('utf-8') if path == 'package.json' else None
    async def missing(*_): return None
    async def readme(directory, maximum, signal):
        calls.append(dict(directory=directory, maximum=maximum)); return dict(path=directory+'/README.md', bytes=b'# Repository')
    files = SimpleNamespace(key='npm:a@1', read=read, readme=missing)
    target = SimpleNamespace(key='git:repo#HEAD', readme=readme)
    def repositories(repo, ref, options): calls.append(dict(repository=repo, ref=ref)); return target
    details = reader(repositories, lambda value:value)
    result = await details.read(dict(files=files, dir='', repository='manifest'), ['en'])
    assert result['origin'] == 'repository' and result['markdown'] == '# Repository'
    assert calls == [dict(repository=repository, ref=None), dict(directory='packages/a', maximum=100)]


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [b'null', b'[]', b'{', b'{"repository":NaN}', b'\xef\xbb\xbf{}'])
async def test_malformed_or_empty_manifest_names_no_repository(payload):
    async def read(*_): return payload
    files = SimpleNamespace(read=read)
    details = reader(manifest_repository=lambda value: None)
    assert await details.manifest_repository_of(files, '', AbortController().signal) is None


def test_document_identity_uses_js_utf8_replacement_for_lone_surrogate():
    details = reader(clock=lambda: 0); files = SimpleNamespace(key='npm:\ud800@1')
    result = details.found('readme', files, 'README.md', '# Doc')
    assert result['document'] == hashlib.sha256('npm:\ufffd@1\0README.md'.encode('utf-8')).hexdigest()[:32]
