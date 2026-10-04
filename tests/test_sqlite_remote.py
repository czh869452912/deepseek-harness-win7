import asyncio
import json

import pytest
import yaml

from dsh.boot.profile_boot import run_profile
from dsh.core.abort import AbortController
from dsh.session.persistence_sqlite_canonical import SqliteSessionPersistence
from dsh.typert.dispatch import RemoteDispatcher
from test_session_remote import local_llm


@pytest.mark.asyncio
@pytest.mark.parametrize('preset', ['minimal', 'standard', 'cordis'])
async def test_canonical_sqlite_remote_model_fork_search_and_cold_restart(tmp_path, monkeypatch, preset, local_llm):
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    database = tmp_path / 'sessions.db'
    patch = tmp_path / 'sqlite.yml'
    patch.write_text(yaml.safe_dump([
        dict(id='session-persistence-jsonl', disabled=True),
        dict(insert=[dict(id='canonical-sqlite', name='@deepseek-ai/dsh-session-persistence-sqlite', config=dict(path=str(database)))]),
        dict(id='session-query-sqlite', config=dict(path=':memory:', openAt='first-search')),
    ]), encoding='utf-8')
    options = dict(profile='web', dshHome=str(tmp_path / 'home'), patchFiles=[str(patch)],
                   args=['--no-open', '--port', '0'], waitForExit=False)
    first = await run_profile(options)
    context = first['ctx']
    stream = None
    try:
        storage = context.get('sessionPersistence')
        assert isinstance(storage, SqliteSessionPersistence)
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
        assert storage.store.database.prepare('PRAGMA user_version').get()['user_version'] == 19
        assert storage.store.database.prepare('SELECT count(*) AS count FROM events').get()['count'] > 0
    finally:
        if stream is not None:
            await stream.aclose()
        first['shutdown'].shutdown(0)
        await first['shutdown'].wait()
    second = await run_profile(options)
    fresh = second['ctx']
    try:
        assert isinstance(fresh.get('sessionPersistence'), SqliteSessionPersistence)
        assert fresh.get('sessions').get(created['sessionId']) is None
        remote = RemoteDispatcher(fresh)
        results = await remote.invoke(dict(namespace='session', method='search', args=dict(request=dict(query='Verified browser reply'))))
        assert {row['sessionId'] for row in results['items']} == {created['sessionId'], forked['sessionId']}
        await fresh.get('sessionController').agents.resolve(created['sessionId'])
        restored = fresh.get('agents').get(created['sessionId'])
        assert any(event['type'] == 'assistant/message' and 'Verified browser reply' in json.dumps(event) for event in restored.session.events)
    finally:
        second['shutdown'].shutdown(0)
        await second['shutdown'].wait()
