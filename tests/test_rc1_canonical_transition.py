"""rc.1 default publication, physical compatibility, and actual cold consumers."""
import hashlib
import inspect
import json
from pathlib import Path

import pytest
import yaml

from dsh.boot.profile_boot import run_profile
from dsh.core.session import Session, SessionHeader, SessionStore
from dsh.core.session.types import validate_session_header
from dsh.api.session_history import wire_header
from dsh.session.persistence_jsonl_canonical import JsonlSessionPersistence
from dsh.session.persistence_sqlite_canonical import SqliteSessionPersistence
from dsh.session.sqlite_legacy_reader import LegacySqliteSessionReader
from dsh.typert.remote import RemoteError
from dsh.typert.dispatch import TypertGatewayError, rpc_failure


def events():
    return [dict(type='turn/start', seq=0, time=1, data=dict(turn=1)),
            dict(type='turn/end', seq=1, time=2, data=dict(turn=1, reason=dict(kind='completed')))]


def test_default_header_and_empty_fork_have_distinct_lineage():
    store = SessionStore()
    parent = store.create('parent')
    child = store.fork(parent, None, 'child')
    assert parent.header.isSeeded is False
    assert child.header.isSeeded is True
    assert child.inheritedEventCount == 0
    assert 'seedLength' not in child.header.to_dict()
    assert wire_header(child.header, 0)['seedLength'] == 0
    assert 'seedLength' not in wire_header(parent.header, 0)
    with pytest.raises(ValueError, match='isSeeded must be a boolean'):
        validate_session_header('parent', dict(version=0, id='parent', createdAt=1))
    with pytest.raises(ValueError, match='invalid field "seedLength"'):
        validate_session_header('parent', dict(version=0, id='parent', createdAt=1, seedLength=0))


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['none', 'zstd'])
@pytest.mark.parametrize('cut', [0, 2])
async def test_physical_version_zero_cold_restore_keeps_exact_cut(tmp_path, compression, cut):
    header = SessionHeader('child', created_at=1, parent_session='parent', is_seeded=True)
    writer = JsonlSessionPersistence(str(tmp_path), compression=compression)
    with pytest.raises(TypeError, match='requires an inherited event count'):
        await writer.create(header)
    await writer.create(header, cut)
    if cut == 2:
        with pytest.raises(ValueError, match='inherited prefix is complete'):
            await writer.append('child', events()[:1])
        assert await writer.read_raw('child') is None
    await writer.append('child', events())
    raw = await writer.read_raw('child')
    physical = json.loads(raw['content'].splitlines()[0])
    assert physical['seedLength'] == cut
    assert 'isSeeded' not in physical
    await writer.close()
    reader = JsonlSessionPersistence(str(tmp_path), compression=compression)
    try:
        inspected = await reader.inspect('child')
        assert inspected.meta.isSeeded is True
        assert inspected.inheritedEventCount == cut
        assert (await reader.read_from('child', 1)).inheritedEventCount == cut
        prepared = await reader.prepare('child')
        try:
            assert prepared.session.inheritedEventCount == cut
            assert prepared.session.firstLiveSeq == 2
            assert prepared.session.ownEvents()[0]['seq'] == cut
        finally:
            prepared.dispose()
    finally:
        await reader.prepared().drain()
        await reader.close()


def test_remote_failures_keep_domain_and_gateway_vocabulary():
    domain = RemoteError('session/not-found', 'missing session', dict(sessionId='missing'))
    assert rpc_failure(domain)['error'] == domain.failure
    gateway = TypertGatewayError('lookup-not-found', 'session/prompt', 'missing', 'sessionId')
    assert rpc_failure(gateway)['error'] == dict(code='gateway/lookup-not-found',
        message=str(gateway), details=dict(endpoint='session/prompt', field='sessionId'))


@pytest.mark.asyncio
async def test_legacy_reader_real_profile_export_preserves_database(tmp_path, monkeypatch):
    source = tmp_path / 'legacy.db'
    writer = SqliteSessionPersistence(str(source), journal_mode='delete')
    header = SessionHeader('child', created_at=1, parent_session='parent', is_seeded=True)
    await writer.create(header, 2)
    await writer.append('child', events())
    await writer.close()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    patch = tmp_path / 'reader.yml'
    patch.write_text(yaml.safe_dump([dict(insert=[dict(id='legacy-reader',
        # Retained reader is an explicit Python extension, not a package
        # in the current upstream installation dependency graph.
        name=str(Path(__file__).resolve().parents[1] / 'dsh/session/sqlite_legacy_reader.py')
             + ':LegacySqliteSessionReaderPlugin', config=dict(path=str(source)))])]), encoding='utf-8')
    result = await run_profile(dict(profile='web', dshHome=str(tmp_path / 'home'), patchFiles=[str(patch)],
        args=['--no-open', '--port', '0'], waitForExit=False))
    ctx = result['ctx']
    try:
        reader = ctx.get('legacySessionReader')
        assert reader is not None
        assert Path(inspect.getfile(type(reader))).resolve() == Path(inspect.getfile(LegacySqliteSessionReader)).resolve()
        assert (await reader.inspect('child')).inheritedEventCount == 2
        location = await reader.export('child', str(tmp_path / 'jsonl'), 'none')
        assert location.kind == 'jsonl'
        with pytest.raises(ValueError, match='persisted log'):
            await reader.export('child', str(tmp_path / 'jsonl'), 'none')
        with pytest.raises(Exception, match='readonly'):
            reader._backend.store.database.exec('DELETE FROM sessions')
        assert ctx.get('sessionPersistence') is not reader
    finally:
        await ctx.fiber.dispose()
    assert ctx.get('legacySessionReader') is None
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    exported = JsonlSessionPersistence(str(tmp_path / 'jsonl'), compression='none')
    try:
        assert (await exported.inspect('child')).inheritedEventCount == 2
    finally:
        await exported.prepared().drain()
        await exported.close()
