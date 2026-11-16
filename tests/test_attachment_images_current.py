"""Current image provider, shared cancellation, immutable publication and consumers."""
import asyncio
import copy
import io
import json
import os
import threading
from pathlib import Path

import pytest
from PIL import Image

from dsh.attachment.error import AttachmentError
from dsh.attachment.store_current import CurrentAttachmentStore, CurrentLocalAttachmentStore
from dsh.attachment.local import object_path
from dsh.core.abort import AbortController
from scripts.oracles.attachment_images_current_python import execute

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'scripts/oracles/attachment_images_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['case'])
def test_actual_current_image_contract(case):
    result = execute(case)
    assert result == case['expected']
    if case['operation'] == 'read' and not case.get('config') and not case.get('policy'):
        assert result['result']['bytes'] == 77 and result['repeatEqual'] is True
    if case['operation'] == 'shared':
        assert result['started'] == 1 and result['second']['value']['bytes'] == 77
    if case['operation'] == 'replace':
        assert result['started'] == 2 and result['replacement'] == result['third']
    if case['operation'] == 'limiter':
        assert result['before'] == [0, 1] and result['peak'] == 2 and result['order'] == list(range(5))


@pytest.fixture
def store(tmp_path):
    value = CurrentLocalAttachmentStore(config=dict(dshHome=str(tmp_path)))
    yield value
    for parent, _, files in os.walk(str(tmp_path)):
        for name in files:
            os.chmod(os.path.join(parent, name), 0o600)


def image_input(alpha=False, size=(300, 200)):
    output = io.BytesIO()
    Image.new('RGBA' if alpha else 'RGB', size, (10, 20, 30, 80) if alpha else (10, 20, 30)).save(output, 'PNG')
    return dict(data=output.getvalue(), mediaType='image/png')


@pytest.mark.asyncio
@pytest.mark.parametrize('alpha', [False, True])
async def test_async_request_derives_and_repairs_cache_with_separate_codec_identity(store, alpha):
    ref = await store.saveImage(image_input(alpha))
    path = Path(store.imageHostPath(ref))
    assert not path.stat().st_mode & 0o200
    from dsh.attachment.image_codec import dimensions
    width, height = dimensions(ref['width'], ref['height'], 1000)
    policy = dict(width=width, height=height, maxBytes=10000)
    projected = await store.readImageRequest(ref, policy)
    assert projected['attachment'] is ref
    assert projected['width'] * projected['height'] <= 1000
    assert projected['hasAlpha'] is alpha and projected['space'] == 'srgb' and projected['depth'] == 'uchar'
    cache = Path(store.root) / 'request-images' / projected['variantId'][7:9] / projected['variantId'][7:]
    assert cache.read_bytes() == projected['data']
    cache.write_bytes(b'broken cache')
    assert (await store.readImageRequest(ref, policy))['data'] == projected['data']
    with Image.open(io.BytesIO(projected['data'])) as decoded:
        decoded.load()
        assert decoded.size == (projected['width'], projected['height'])
        assert ('A' in decoded.getbands()) is alpha


@pytest.mark.asyncio
async def test_batch_failure_publishes_nothing_and_validate_does_not_write(store):
    valid = image_input()
    await store.validateImage(valid)
    assert not Path(store.root).exists()
    with pytest.raises(AttachmentError):
        await store.saveImages([valid, dict(data=b'not an image', mediaType='image/png')])
    assert not Path(store.root).exists()


@pytest.mark.asyncio
async def test_current_images_verify_existing_objects_instead_of_overwriting(store):
    input_data = image_input()
    ref = await store.saveImage(input_data)
    path = Path(object_path(store.root, ref['attachmentId'][7:]))
    os.chmod(str(path), 0o600)
    path.write_bytes(b'corrupt')
    with pytest.raises(AttachmentError) as caught:
        await store.saveImage(input_data)
    assert caught.value.code == 'ATTACHMENT_CORRUPT'
    assert path.read_bytes() == b'corrupt'
    assert list((Path(store.root) / 'tmp').iterdir()) == []


@pytest.mark.asyncio
async def test_base_projection_observes_abort_reason_before_unsupported_error():
    controller = AbortController()
    reason = RuntimeError('already cancelled')
    controller.abort(reason)
    with pytest.raises(RuntimeError) as caught:
        await CurrentAttachmentStore().readImageRequest({}, {}, controller.signal)
    assert caught.value is reason
    with pytest.raises(AttachmentError) as caught:
        await CurrentAttachmentStore().readImageRequest({}, {})
    assert caught.value.code == 'ATTACHMENT_PROJECTION_UNSUPPORTED'


@pytest.mark.asyncio
async def test_compression_slot_is_held_until_cancelled_worker_finishes(store, monkeypatch):
    from dsh.attachment import local
    store.compression._slots = asyncio.Semaphore(1)
    entered, release = threading.Event(), threading.Event()
    real = local.prepare_image_file
    calls = []
    def blocked(*args):
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return real(*args)
    monkeypatch.setattr(local, 'prepare_image_file', blocked)
    first = asyncio.ensure_future(store.validateImage(image_input()))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    first.cancel()
    second = asyncio.ensure_future(store.validateImage(image_input()))
    await asyncio.sleep(0.02)
    assert len(calls) == 1 and not first.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_pi_consumer_prefers_async_capability_and_passes_signal():
    from dsh.llm.pi_context import to_pi_context_with_images
    fixtures = json.loads((ROOT / 'scripts/oracles/pi-fixtures.json').read_text(encoding='utf-8'))
    options = copy.deepcopy(next(row for row in fixtures if row['id'] == 'context-duplicate-image')['options'])
    signal = AbortController().signal
    options['signal'] = signal
    calls = []
    class Store:
        async def readImageRequest(self, ref, policy, received):
            assert received is signal
            calls.append(ref)
            return dict(data=b'abcdef', bytes=6, width=2, height=2, mediaType='image/png')
        def read_image_request(self, *_args):
            pytest.fail('current async provider must be used')
    result = await to_pi_context_with_images(options, Store(), lambda ref: None)
    assert len(calls) == 1 and result['messages'][0]['content'][-1]['type'] == 'image'
