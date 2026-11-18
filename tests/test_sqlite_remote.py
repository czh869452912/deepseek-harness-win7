import asyncio
import hashlib
from dsh.core.session import SessionHeader
from dsh.session.sqlite_legacy_reader import LegacySqliteSessionReader
from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistence as JsonlSessionPersistence
import json
from pathlib import Path

import pytest
import yaml

from dsh.boot.profile_boot import run_profile
from dsh.core.abort import AbortController
from dsh.session.persistence_sqlite_canonical import SqliteSessionPersistence
from dsh.typert.dispatch import RemoteDispatcher
from test_session_remote import local_llm


@pytest.mark.asyncio
@pytest.mark.parametrize('preset', ['minimal', 'standard', 'cordis'])
async def test_legacy_sqlite_export_remote_model_fork_search_and_cold_restart(tmp_path, monkeypatch, preset, local_llm):
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    database = tmp_path / 'sessions.db'
    writer = SqliteSessionPersistence(str(database), journal_mode='delete')
    await writer.create(SessionHeader('legacy-history', created_at=1, cwd=str(tmp_path)))
    await writer.append('legacy-history', [
        dict(type='turn/start', seq=0, time=1, data=dict(turn=1)),
        dict(type='step/start', seq=1, time=2, data=dict(turn=1, step=1)),
        dict(type='user/message', seq=2, time=3, surfaceOp='append', data=dict(
            id='legacy-message', role='user', source=dict(kind='user'),
            content=[dict(type='text', text='Legacy history remains searchable')])),
        dict(type='step/end', seq=3, time=4, data=dict(turn=1, step=1)),
        dict(type='turn/end', seq=4, time=5, data=dict(turn=1, reason=dict(kind='completed'))),
    ])
    await writer.close()
    original = hashlib.sha256(database.read_bytes()).hexdigest()
    logs = tmp_path / 'canonical-logs'
    reader = LegacySqliteSessionReader(str(database))
    try:
        await reader.export('legacy-history', str(logs), compression='none')
    finally:
        await reader.close()
    patch = tmp_path / 'sqlite-reader.yml'
    patch.write_text(yaml.safe_dump([
        dict(id='session-persistence-jsonl', config=dict(root=str(logs), compression='none')),
        dict(insert=[dict(id='legacy-sqlite-reader', name=str(Path(__file__).resolve().parents[1] / 'dsh/session/sqlite_legacy_reader.py') + ':LegacySqliteSessionReaderPlugin', config=dict(path=str(database)))]),
        dict(id='session-query-sqlite', config=dict(path=':memory:', openAt='first-search')),
    ]), encoding='utf-8')
    options = dict(profile='web', dshHome=str(tmp_path / 'home'), patchFiles=[str(patch)],
                   args=['--no-open', '--port', '0'], waitForExit=False)
    first = await run_profile(options)
    context = first['ctx']
    stream = None
    try:
        storage = context.get('sessionPersistence')
        assert isinstance(storage, JsonlSessionPersistence)
        remote = RemoteDispatcher(context)
        created = await remote.invoke(dict(namespace='session', method='create',
            args=dict(request=dict(cwd=str(tmp_path), sessionId='canonical-remote', agentPreset=preset))))
        controller = context.get('sessionController')
        stream = controller.follow(dict(address=dict(kind='session', sessionId=created['sessionId'])), AbortController().signal)
        await stream.__anext__()
        await controller.prompt(dict(sessionId=created['sessionId'], requestId='canonical-prompt', mode='queue',
            content=[dict(type='text', text='Please provide the durable reply.')]), AbortController().signal)
        async def complete():
            async for frame in stream:
                if frame['type'] == 'event' and frame['event']['type'] == 'turn/end':
                    return
        await asyncio.wait_for(complete(), 15)
        await context.get('agents').get(created['sessionId']).session.flush()
        results = await remote.invoke(dict(namespace='session', method='search', args=dict(request=dict(query='Verified browser reply'))))
        assert results['items'][0]['sessionId'] == created['sessionId']
        forked = await remote.invoke(dict(namespace='session', method='fork', args=dict(request=dict(sessionId=created['sessionId']))))
        assert forked['sessionId'] != created['sessionId']
        assert local_llm and database.is_file()
        assert (await context.get('legacySessionReader').inspect('legacy-history')).inheritedEventCount == 0
        assert hashlib.sha256(database.read_bytes()).hexdigest() == original
    finally:
        if stream is not None:
            await stream.aclose()
        first['shutdown'].shutdown(0)
        await first['shutdown'].wait()
    second = await run_profile(options)
    fresh = second['ctx']
    try:
        assert isinstance(fresh.get('sessionPersistence'), JsonlSessionPersistence)
        assert fresh.get('sessions').get(created['sessionId']) is None
        remote = RemoteDispatcher(fresh)
        results = await remote.invoke(dict(namespace='session', method='search', args=dict(request=dict(query='Verified browser reply'))))
        assert {row['sessionId'] for row in results['items']} == {created['sessionId'], forked['sessionId']}
        await fresh.get('sessionController').agents.resolveAgent(created['sessionId'])
        legacy = await remote.invoke(dict(namespace='session', method='search', args=dict(request=dict(query='Legacy history'))))
        assert legacy['items'][0]['sessionId'] == 'legacy-history'
        assert hashlib.sha256(database.read_bytes()).hexdigest() == original
        restored = fresh.get('agents').get(created['sessionId'])
        assert any(event['type'] == 'assistant/message' and 'Verified browser reply' in json.dumps(event) for event in restored.session.events)
    finally:
        second['shutdown'].shutdown(0)
        await second['shutdown'].wait()
