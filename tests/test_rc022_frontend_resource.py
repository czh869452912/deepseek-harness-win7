import asyncio
import threading
import pytest

from dsh.host.frontend_static import current
from scripts.rc022_frontend_resource_probe import observe


@pytest.mark.asyncio
async def test_authenticated_frontend_resource_and_live_peer_boot_documents(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 25
    assert rows['anonymous-index']['response']['status'] == 401
    assert rows['browser-exchange']['response']['status'] == 303
    assert rows['browser-exchange']['version'] == 'v1'
    owner = rows['browser:GET:/']['response']['body']
    guest = rows['reader:/']['response']['body']
    assert owner['snapshot'] == dict(type='baseline', owner=True)
    assert owner['browser'] is True
    assert guest['snapshot'] == dict(type='baseline', owner=False, grants=[dict(resource=dict(kind='session', id='visible'), actions=['notes/read'])])
    assert guest['browser'] is False
    assert owner['base'] == guest['base'] == ['./']
    assert owner['baseFirst'] and guest['baseFirst']
    assert rows['api-cookie-index']['response']['status'] == rows['wrong-audience-index']['response']['status'] == 401
    assert rows['public:/icon.png']['response']['headers']['content-type'] == 'image/png'
    assert rows['public:/blob.bin']['response']['body'] == [0, 255, 1]
    assert rows['public:/..%2f..%2fsecret']['response']['status'] == 403
    assert rows['public:/bad%']['response']['status'] == rows['public:/bad%00path']['response']['status'] == 400
    assert rows['revalidated']['http']['status'] == rows['revalidated']['reader']['status'] == 304
    assert rows['rebuilt']['response']['status'] == 200
    assert rows['rebuilt']['response']['headers']['etag'] != rows['revalidated']['http']['headers']['etag']
    assert 'etag' not in rows['index-not-cached']['response']['headers']
    assert rows['methods']['http']['status'] == rows['methods']['reader']['status'] == 405
    assert rows['index-removed']['http']['status'] == rows['index-removed']['reader']['status'] == 404
    assert rows['frontend-unload']['http']['status'] == rows['frontend-unload']['reader']['status'] == 404


def test_candidate_static_config_requires_explicit_dist_anchor():
    with pytest.raises(Exception): current.CurrentFrontendStatic.Config({})
    with pytest.raises(Exception): current.CurrentFrontendStatic.Config(dict(distIndex=1))
    assert current.CurrentFrontendStatic.Config(dict(distIndex='C:/dist/index.html')) == dict(distIndex='C:/dist/index.html')


@pytest.mark.asyncio
async def test_cancelled_file_read_joins_its_owned_executor_operation(tmp_path, monkeypatch):
    path = tmp_path / 'asset.bin'; path.write_bytes(b'owned')
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original = current.read_bytes
    def read(target):
        entered.set()
        assert release.wait(2)
        try: return original(target)
        finally: done.set()
    monkeypatch.setattr(current, 'read_bytes', read)
    task = asyncio.create_task(current.read_owned(str(path)))
    try:
        async def started():
            while not entered.is_set(): await asyncio.sleep(0)
        await asyncio.wait_for(started(), 1)
        task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not done.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert done.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
