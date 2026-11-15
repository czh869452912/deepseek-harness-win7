import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.core.abort import AbortController
from dsh.host.file_upload_authorized import AuthorizedFileUploads
from dsh.typert.remote import RemoteError
from scripts.rc022_upload_probe import observe


@pytest.mark.asyncio
async def test_typed_upload_receipts_and_mixed_prompt_budgets(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 14
    assert rows['typed-image']['value']['encodedBytes'] == 3
    assert rows['typed-image']['value']['type'] == 'image'
    assert rows['typed-image']['foreign'] is rows['typed-image']['command'] is None
    assert rows['typed-file']['command'] == rows['typed-file']['value']['attachment']
    assert rows['rollback']['retained'] is True
    assert rows['committed']['retained'] is False
    assert [part['type'] for part in rows['mixed-at-limit']['value']] == ['image', 'image']
    assert rows['mixed-over-bytes']['error']['code'] == 'IMAGES_TOO_LARGE'
    assert rows['mixed-over-count']['error']['code'] == 'TOO_MANY_IMAGES'
    assert rows['upload-over-limit']['error']['details']['reason'] == 'IMAGE_TOO_LARGE'
    assert rows['unsupported']['error']['details']['reason'] == 'UNSUPPORTED_IMAGE_TYPE'
    assert rows['cancelled']['error']['code'] == 'gateway/internal'
    assert rows['image-route']['ok'] is True
    assert rows['writes']['values'] == [[3], [3], [2]]
    assert rows['unloaded'] == dict(name='unloaded', routes=0, resolvers=0)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_image_upload_races_do_not_mint_receipts_after_storage(cancel, tmp_path, monkeypatch):
    from io import BytesIO
    import os
    from PIL import Image
    from dsh.cordis import Context
    from dsh.attachment.store_current import CurrentLocalAttachmentStore
    ctx = Context()
    store = CurrentLocalAttachmentStore(ctx, dict(dshHome=str(tmp_path)))
    agent = NS(id='one', session=NS(header=NS(origin='user')))
    live = {'one': agent}
    ctx.set_service('agents', NS(get=live.get))
    ctx.set_service('commands', NS(registerFileReceiptResolver=lambda _: lambda: None))
    ctx.set_service('connection', NS(fetch=NS(register=lambda _: lambda: None)))
    entered, release = asyncio.Event(), asyncio.Event()
    controller = AbortController()
    original = store.saveImages
    async def save(inputs):
        refs = await original(inputs)
        entered.set()
        await release.wait()
        return refs
    monkeypatch.setattr(store, 'saveImages', save)
    data = BytesIO()
    Image.new('RGB', (1, 1), 'red').save(data, format='PNG')
    async def chunks():
        yield data.getvalue()
    task = None
    try:
        await ctx.plugin(AuthorizedFileUploads)
        task = asyncio.create_task(ctx.fileUploads.uploadImageStream(dict(sessionId='one',
            mediaType='image/png', data=chunks(), signal=controller.signal)))
        await asyncio.wait_for(entered.wait(), 5)
        if cancel:
            controller.abort()
        else:
            live.clear()
        release.set()
        with pytest.raises(RemoteError) as caught:
            await task
        assert caught.value.code == ('gateway/internal' if cancel else 'session/not-found')
        assert not list(ctx.fileUploads._staged.items())
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await ctx.fiber.dispose()
        for path in tmp_path.rglob('*'):
            if path.is_file():
                os.chmod(str(path), 0o600)


@pytest.mark.asyncio
async def test_upload_store_preserves_remote_failure_and_rejects_subagent_before_io():
    service = AuthorizedFileUploads.__new__(AuthorizedFileUploads)
    class Context:
        def get(self, name):
            return NS(isAttachmentError=lambda _: False)
    service.ctx = Context()
    agent = NS(session=NS(header=NS(origin='user')))
    error = RemoteError('session/not-found', 'gone', {})
    calls = []
    async def save():
        calls.append(True)
        raise error
    with pytest.raises(RemoteError) as caught:
        await service.store(agent, save)
    assert caught.value is error
    agent.session.header.origin = 'subagent'
    with pytest.raises(RemoteError) as caught:
        await service.store(agent, save)
    assert caught.value.details['reason'] == 'SUBAGENT_FILE_UNSUPPORTED'
    assert len(calls) == 1
