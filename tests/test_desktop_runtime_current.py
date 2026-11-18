"""Real canonical Desktop composition and carrier lifetime regressions."""
import asyncio
import json
from pathlib import Path

import pytest

from dsh.core.abort import AbortController
from dsh.host.desktop.runtime import run_desktop_host, body_bytes


@pytest.mark.asyncio
async def test_canonical_desktop_routes_and_disposal(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    runtime = await run_desktop_host(tmp_path / 'profile')
    signal = AbortController().signal
    async def fetch(path, method='GET', body=None, host='app'):
        return await runtime.fetch(dict(url='dsh-app://' + host + path, method=method,
            headers={'content-type': 'application/json'}, body=body, signal=signal))
    try:
        assert runtime.ctx.get('webServer') is None
        graph = runtime.ctx.get('clientModules').graph()
        index = await fetch('/index.html')
        assert index['status'] == 200
        assert b'globalThis.__DSH_TRANSPORT__' in index['body']
        assert b'ownsHost:true' in index['body']
        assert b'__DSH_BOOT__' in index['body']
        assert (await fetch('/', 'HEAD'))['body'] is None
        bundle = graph['batches'][0]['url']
        direct = await runtime.ctx.get('clientModules').fetchBundle(
            dict(url='dsh-app://app' + bundle, method='GET'))
        assert (await fetch(bundle))['body'] == direct['body']
        assert (await fetch(bundle, 'HEAD'))['body'] is None
        assert (await fetch('/missing'))['status'] == 404
        assert (await fetch('/index.html', host='evil'))['status'] == 403
        assert (await fetch('/%2e%2e/package.json'))['status'] == 403
        assert (await fetch('/%ff'))['status'] == 403
        assert (await fetch('/index.html', 'POST'))['status'] == 405
        request = dict(type='client-request', rpcId='desktop', method='settings/describe', payload={'args': {}})
        response = await fetch('/api/settings/describe', 'POST', json.dumps(request).encode('utf-8'))
        payload = json.loads(response['body'])
        assert response['status'] == 200 and payload['result']['ok']
        assert payload['result']['value']['namespaces']
        assert (await fetch('/.dsh/remote-stream'))['status'] == 405
        assert (await fetch('/.dsh/remote-stream', 'POST', b'[]'))['status'] == 400
        assert (await fetch('/.dsh/remote-stream', 'POST', b'{'))['status'] == 400
        controller = AbortController()
        controller.abort('caller left')
        with pytest.raises(Exception):
            await runtime.fetch(dict(url='dsh-app://app/', method='GET', signal=controller.signal))
    finally:
        await runtime.close()
    await runtime.close()
    assert runtime.ctx.get('clientModules') is None
    with pytest.raises(RuntimeError, match='disposing'):
        await fetch('/')
    # The first Host released its OS lease and can cold-open the same profile.
    second = await run_desktop_host(tmp_path / 'profile')
    await second.close()


@pytest.mark.asyncio
async def test_stream_body_bound_and_iterator_close():
    closed = []
    async def source():
        try:
            yield b'ab'
            yield b'cd'
        finally:
            closed.append(True)
    iterator = source()
    with pytest.raises(ValueError, match='byte limit'):
        await body_bytes(iterator, 3)
    await iterator.aclose()
    assert closed == [True]
    assert await body_bytes(None) == b''
