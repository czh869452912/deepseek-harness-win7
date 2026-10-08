import asyncio
import threading
import os
from pathlib import Path

import pytest

from dsh.cordis import Context
from dsh.core.session import SessionHeader, SessionPlugin
from dsh.session.persistence_jsonl_canonical import JsonlSessionPersistencePlugin, JsonlSessionPersistence
from dsh.session.jsonl_store import JsonlStore, JsonlRollbackError
from dsh.session.jsonl_format import encode_segment, project_key
from dsh.session.jsonl_zstd import compress_frame, scan_frames, decompress_frame


def events():
    return [dict(type='turn/start', seq=0, time=1, data=dict(turn=1)),
        dict(type='turn/end', seq=1, time=2, data=dict(turn=1, reason=dict(kind='completed')))]


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['none', 'zstd'])
async def test_long_session_paths_preserve_append_cold_read_and_public_location(tmp_path, compression):
    root = tmp_path / ('sessions-' + 'a' * 160)
    metadata = SessionHeader('sdk-durable', created_at=1, cwd=str(tmp_path / 'project'))
    provider = JsonlSessionPersistence(str(root), compression)
    location = provider.locate(metadata).path
    assert len(location) > 260 and not location.startswith('\\\\?\\')
    await provider.create(metadata)
    await provider.append(metadata.id, events()[:1])
    await provider.append(metadata.id, events()[1:])
    cold = JsonlSessionPersistence(str(root), compression)
    assert cold.locate(metadata).path == location
    assert cold.store.find(metadata.id) == location
    assert (await cold.read_stored(metadata.id)).events == events()
    assert [header.id for header in await cold.list()] == [metadata.id]
    assert len(await cold.store.list_snapshots()) == 1
    raw = await cold.store.read_raw(metadata.id)
    assert raw['filename'] == 'session.jsonl' and 'turn/end' in raw['content']
    physical = Path('\\\\?\\' + location) if os.name == 'nt' else Path(location)
    before = physical.read_bytes()
    with pytest.raises(ValueError, match='configured for compression'):
        await JsonlSessionPersistence(str(root), 'zstd' if compression == 'none' else 'none').list()
    assert physical.read_bytes() == before


@pytest.mark.asyncio
async def test_canonical_registry_uses_lazy_default_checksummed_zstd(tmp_path):
    from dsh.boot.plugin_registry import resolve_harness_plugin
    assert resolve_harness_plugin('@deepseek-ai/dsh-session-persistence-jsonl') is JsonlSessionPersistencePlugin
    context = Context()
    await context.plugin(SessionPlugin)
    await context.plugin(JsonlSessionPersistencePlugin, dict(root=str(tmp_path / 'absent')))
    provider = context.get('sessionPersistence')
    try:
        assert provider.compression == 'zstd'
        assert not Path(provider.root).exists()
        metadata = SessionHeader('中文😀', created_at=1)
        await provider.create(metadata)
        assert not Path(provider.root).exists()
        await provider.append(metadata.id, events())
        path = Path(provider.locate(metadata).path)
        assert path.name == 'session.jsonl.zstd'
        buffer = path.read_bytes()
        frames = scan_frames(buffer)['frames']
        assert len(frames) == 2
        for frame in frames:
            assert buffer[frame['start'] + 4] & 4
            assert decompress_frame(buffer[frame['start']:frame['end']]).endswith(b'\n')
        loaded = await provider.load(metadata.id)
        assert loaded.events == events()
        raw = await provider.read_raw(metadata.id)
        assert raw['filename'] == 'session.jsonl'
        assert raw['content'].count('\n') == 3
    finally:
        await context.fiber.dispose()
    assert context.get('sessionPersistence') is None


@pytest.mark.parametrize('compression', ['zstd', 'none'])
@pytest.mark.asyncio
async def test_torn_tail_inspection_is_inert_and_load_commits_repair(tmp_path, compression):
    provider = JsonlSessionPersistence(str(tmp_path), compression)
    metadata = SessionHeader('tail', created_at=1)
    await provider.create(metadata)
    await provider.append(metadata.id, events()[:1])
    path = Path(provider.locate(metadata).path)
    tail = compress_frame(b'{"torn":')[:-1] if compression == 'zstd' else b'{"torn":'
    with path.open('ab') as stream:
        stream.write(tail)
    before = path.read_bytes()
    inspected = await provider.inspect(metadata.id)
    assert [event['type'] for event in inspected.events] == ['turn/start', 'turn/end']
    assert path.read_bytes() == before
    loaded = await provider.load(metadata.id)
    assert loaded.events == inspected.events
    assert path.read_bytes() != before
    restored = JsonlSessionPersistence(str(tmp_path), compression)
    assert (await restored.load(metadata.id)).events == loaded.events
    prepared = await restored.prepare(metadata.id)
    try:
        assert prepared.session.events[-1]['type'] == 'session/end-seed'
        assert prepared.session.events[:-1] == loaded.events
    finally:
        prepared.dispose()
        await restored.prepared().drain()
        await provider.prepared().drain()


@pytest.mark.asyncio
async def test_encoding_refusal_preserves_original_artifact(tmp_path):
    plain = JsonlSessionPersistence(str(tmp_path), 'none')
    metadata = SessionHeader('plain', created_at=1)
    await plain.create(metadata)
    await plain.append(metadata.id, events())
    path = Path(plain.locate(metadata).path)
    before = path.read_bytes()
    compressed = JsonlSessionPersistence(str(tmp_path))
    with pytest.raises(ValueError, match='configured for compression "zstd"'):
        await compressed.list()
    assert path.read_bytes() == before
    assert not list(tmp_path.rglob('*.zstd'))


def test_jsonl_paths_encode_original_utf16_units():
    assert encode_segment('中文😀\ud800~') == '~4E2D~6587~D83D~DE00~D800~007E'
    assert project_key('C:\\工作\\😀') == '--C-~5DE5~4F5C-~D83D~DE00--'
    assert encode_segment('..') == '~002E~002E'


@pytest.mark.asyncio
async def test_cancelled_read_drains_actual_worker_before_return(tmp_path, monkeypatch):
    store = JsonlStore(str(tmp_path))
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def blocked(path, signal):
        entered.set()
        try:
            assert release.wait(5)
            return b'', 'same', 'same'
        finally:
            finished.set()
    monkeypatch.setattr(store, '_read_file', blocked)
    pending = asyncio.create_task(store.read_stable('unused'))
    while not entered.is_set():
        await asyncio.sleep(0.01)
    try:
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done() and not finished.is_set()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert finished.is_set()


@pytest.mark.asyncio
async def test_revision_change_retries_actual_file_read(tmp_path, monkeypatch):
    from dsh.session import jsonl_store
    store = JsonlStore(str(tmp_path))
    path = tmp_path / 'data'
    path.write_bytes(b'first')
    original = jsonl_store.file_revision
    observed = []
    def changing(location):
        revision = original(location)
        observed.append(revision)
        if len(observed) == 1:
            path.write_bytes(b'second-larger')
        return revision
    monkeypatch.setattr(jsonl_store, 'file_revision', changing)
    content, revision = await store.read_stable(str(path))
    assert len(observed) == 4
    assert content == b'second-larger' and revision == original(str(path))


@pytest.mark.parametrize('rollback_fails', [False, True])
@pytest.mark.asyncio
async def test_append_sync_failure_restores_prefix_or_retains_both_causes(tmp_path, monkeypatch, rollback_fails):
    from dsh.session import jsonl_store
    store = JsonlStore(str(tmp_path), 'none')
    metadata = SessionHeader('rollback', created_at=1).to_dict()
    await store.append_batch(metadata, events()[:1], False)
    path = Path(store.locate(metadata))
    before = path.read_bytes()
    original = jsonl_store.os.fsync
    failure, rollback = OSError('controlled sync failure'), OSError('controlled rollback failure')
    calls = []
    def sync(descriptor):
        calls.append(descriptor)
        if len(calls) == 1:
            raise failure
        return original(descriptor)
    monkeypatch.setattr(jsonl_store.os, 'fsync', sync)
    if rollback_fails:
        def refuse(path, size):
            raise rollback
        monkeypatch.setattr(store, '_truncate', refuse)
    with pytest.raises(JsonlRollbackError if rollback_fails else OSError) as observed:
        await store.append_batch(metadata, events()[1:], True)
    if rollback_fails:
        assert observed.value.errors == [failure, rollback]
        assert str(observed.value) == 'failed to roll back append to "%s"' % path
    else:
        assert observed.value is failure and path.read_bytes() == before
