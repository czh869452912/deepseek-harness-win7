import asyncio
from collections import OrderedDict
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.office.browser_engine import BrowserConverter, BrowserOfficeEngine, _State
from dsh.office.contracts import resolve_request
from dsh.office.errors import OfficeKitError
from dsh.office.font_volume import FontVolume


class State:
    def __init__(self, volume=None):
        self.volume = volume or FontVolume([])
        self.cache = OrderedDict()

    async def acquire(self, signal):
        signal.throwIfAborted()
        records = [dict(path=path) for path in self.volume.sources]
        return self.volume, {}, dict(generation='generation', faces=[], records=records)

    def merge(self, generation, messages):
        pass


def converter(tmp_path, worker, timeout=200, state=None):
    options = resolve_request('options', dict(fontDirectories=[], fontMetadataCacheDirectory=False, timeoutMs=timeout))
    engine = SimpleNamespace(temporary_directory=str(tmp_path), _worker=worker, converters=set())
    value = BrowserConverter(engine, options, state or State())
    engine.converters.add(value)
    return value


def response():
    return dict(ok=True, output=b'exported', metadata=dict(backend='wasm', missingFonts=[]), adapter=dict(openDescriptors=0, retainedReadBuffers=0))


def request(tmp_path, name='output.txt'):
    path = tmp_path / 'input.docx'
    path.write_bytes(b'input')
    return dict(inputPath=str(path), outputPath=str(tmp_path / name))


@pytest.mark.asyncio
async def test_queued_abort_preserves_reason_without_creating_output(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def worker(*args):
        entered.set()
        await release.wait()
        return response()
    owner = converter(tmp_path, worker, timeout=2000)
    first = asyncio.create_task(owner.convert(request(tmp_path, 'first.txt')))
    await entered.wait()
    controller = AbortController()
    reason = RuntimeError('queued stopped')
    second = asyncio.create_task(owner.convert(request(tmp_path, 'second.txt'), controller.signal))
    await asyncio.sleep(.06)
    controller.abort(reason)
    with pytest.raises(RuntimeError) as caught:
        await second
    assert caught.value is reason and not (tmp_path / 'second.txt').exists()
    release.set()
    assert (await first)['backend'] == 'wasm'
    await owner.dispose()
    assert not owner.engine.converters


@pytest.mark.asyncio
async def test_queue_wait_does_not_consume_conversion_deadline(tmp_path):
    entered = asyncio.Event()
    calls = []
    async def worker(payload, assets, signal):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            await signal.wait_aborted()
            signal.throwIfAborted()
        return response()
    owner = converter(tmp_path, worker, timeout=250)
    first = asyncio.create_task(owner.convert(request(tmp_path, 'first.txt')))
    await entered.wait()
    second = asyncio.create_task(owner.convert(request(tmp_path, 'second.txt')))
    with pytest.raises(OfficeKitError) as caught:
        await first
    assert caught.value.code == 'timeout' and caught.value.message == 'LibreOffice conversion timed out.'
    assert (await second)['backend'] == 'wasm'
    assert not (tmp_path / 'first.txt').exists()
    assert (tmp_path / 'second.txt').read_bytes() == b'exported'
    await owner.dispose()


@pytest.mark.asyncio
async def test_disposal_aborts_and_joins_before_owned_scratch_is_released(tmp_path):
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def worker(payload, assets, signal):
        entered.set()
        await signal.wait_aborted()
        cleanup.set()
        await release.wait()
        signal.throwIfAborted()
    owner = converter(tmp_path, worker, timeout=2000)
    task = asyncio.create_task(owner.convert(request(tmp_path)))
    await entered.wait()
    disposal = owner.dispose()
    await cleanup.wait()
    assert not disposal.done() and (tmp_path / 'output.txt').exists()
    release.set()
    with pytest.raises(RuntimeError, match='disposed'):
        await task
    await disposal
    assert not (tmp_path / 'output.txt').exists()
    assert not list(tmp_path.glob('dsh-office-*'))


@pytest.mark.asyncio
async def test_repeated_caller_cancellation_drains_worker_cleanup(tmp_path):
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def worker(payload, assets, signal):
        entered.set()
        await signal.wait_aborted()
        cleanup.set()
        await release.wait()
        signal.throwIfAborted()
    owner = converter(tmp_path, worker, timeout=2000)
    task = asyncio.create_task(owner.convert(request(tmp_path)))
    await entered.wait()
    task.cancel()
    await cleanup.wait()
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done() and (tmp_path / 'output.txt').exists()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / 'output.txt').exists()
    assert not list(tmp_path.glob('dsh-office-*'))
    await owner.dispose()


@pytest.mark.asyncio
async def test_changed_physical_font_prevents_publication(tmp_path):
    font = tmp_path / 'font.ttf'
    font.write_bytes(b'old-font')
    state = State(FontVolume([str(font)]))
    async def worker(*args):
        font.write_bytes(b'new-font-changed')
        return response()
    owner = converter(tmp_path, worker, state=state)
    with pytest.raises(OfficeKitError, match='system font changed'):
        await owner.convert(request(tmp_path))
    assert not (tmp_path / 'output.txt').exists()
    await owner.dispose()


@pytest.mark.asyncio
async def test_shared_scan_cancellation_does_not_abort_other_consumer(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    async def worker(payload, assets, signal):
        entered.set()
        await release.wait()
        signal.throwIfAborted()
        return dict(ok=True, snapshot=dict(generation='new', faces=[], records=[]), adapter=dict(openDescriptors=0, retainedReadBuffers=0))
    options = resolve_request('options', dict(fontDirectories=[], fontMetadataCacheDirectory=False))
    state = _State(SimpleNamespace(_worker=worker), options)
    first_signal, second_signal = AbortController(), AbortController()
    first = asyncio.create_task(state.acquire(first_signal.signal))
    await entered.wait()
    second = asyncio.create_task(state.acquire(second_signal.signal))
    await asyncio.sleep(.01)
    first_signal.abort(RuntimeError('only first'))
    with pytest.raises(RuntimeError, match='only first'):
        await first
    assert not state.scan['controller'].signal.aborted
    release.set()
    assert (await second)[2]['generation'] == 'new'
    assert state.scan is None


def test_stale_generation_cache_messages_do_not_replace_current_faces():
    state = _State(None, dict(maxFontResolutionEntries=1))
    state.generation = 'new'
    entry = dict(key='a', faces=[dict(path='one', faceIndex=0)], codePoints=[65], emptyRequest=False, missingFamily='first')
    state.merge('old', [dict(entries=[entry])])
    assert not state.cache
    state.merge('new', [dict(entries=[entry])])
    state.merge('new', [dict(entries=[dict(entry, faces=[dict(path='two', faceIndex=1)], codePoints=[66], missingFamily='second')])])
    assert state.cache['a']['codePoints'] == [65, 66]
    assert [face['path'] for face in state.cache['a']['faces']] == ['one', 'two']
    assert state.cache['a']['missingFamily'] == 'first'
    state.merge('new', [dict(entries=[dict(entry, key='b')])])
    assert list(state.cache) == ['b']


@pytest.mark.asyncio
async def test_actual_browser_converter_writes_validated_pdf_and_joins(tmp_path):
    executable = os.environ.get('DSH_TEST_OFFICE_BROWSER')
    root = Path(__file__).resolve().parents[1]
    source = root / '.goose/out/rc022-prep-20261114-01/source'
    if not executable or not source.exists():
        pytest.skip('Explicit actual browser and pinned SDK inputs required.')
    package = source / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
    engine = BrowserOfficeEngine(executable, str(package), temporary_directory=str(tmp_path))
    try:
        owner = await engine.createConverter(dict(fontDirectories=[str(Path(os.environ['WINDIR']) / 'Fonts/arial.ttf')], fontMetadataCacheDirectory=False))
        output = tmp_path / 'output.pdf'
        result = await owner.render(dict(inputPath=str(source / 'packages/bundle/web-app/tests/fixtures/document-conversion.docx'), outputPath=str(output)))
        assert result['backend'] == 'wasm' and result['pageCount'] == 1 and result['missingFonts'] == ['Liberation Sans']
        assert output.read_bytes().startswith(b'%PDF-')
    finally:
        await engine.close()
    assert not engine.converters and not engine.carrier.active
    assert not list(tmp_path.glob('dsh-office-*'))
