import json

import pytest
import yaml

from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import run_profile
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.core.tools import ToolExecutionInput
from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['jsonl', 'jsonl-zstd', 'sqlite'])
async def test_optional_profile_model_tools_next_request_and_cold_restart(tmp_path, backend):
    profile = tmp_path / 'profiles' / 'session-tools'
    init_profile(str(profile), [], 'startup')
    rows = [dict(id=name, name='@deepseek-ai/dsh-' + name) for name in ['session', 'tools', 'system-prompt', 'agent', 'agent-loop']]
    persistence_config = dict(root=str(tmp_path / 'sessions'), compression='none' if backend == 'jsonl' else 'zstd') if backend.startswith('jsonl') else dict(path=str(tmp_path / 'sessions.db'))
    rows.extend([dict(id='storage', name='@deepseek-ai/dsh-session-persistence-' + ('jsonl' if backend.startswith('jsonl') else backend), config=persistence_config),
                 dict(id='query', name='@deepseek-ai/dsh-session-query-sqlite', config=dict(path=str(tmp_path / 'query.db'), defaultLimit=1)),
                 dict(id='history-tools', name='@deepseek-ai/dsh-tool-session-query', config=dict(maxSearchResults=2))])
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([dict(insert=rows)]), encoding='utf-8')
    options = dict(profile='session-tools', dsh_home=str(tmp_path), wait_for_exit=False)
    first = await run_profile(options)
    context = first['ctx']
    adapter = StrictMockLlmAdapter([
        dict(tool_calls=[dict(id='find', name='session_search', arguments=dict(query='needle'))]),
        dict(tool_calls=[dict(id='events', name='session_event_search', arguments=dict(session_id='prior', query='needle'))]),
        dict(tool_calls=[dict(id='lineage', name='session_trace', arguments=dict(session_id='prior'))]),
        dict(tool_calls=[dict(id='relationships', name='session_event_trace', arguments=dict(session_id='prior', seq=0))]),
        dict(tool_calls=[dict(id='exact', name='session_event_read', arguments=dict(session_id='prior', seq=0))]),
        dict(text='The prior history contains the needle.')])
    context.provide('llm', adapter)
    storage = context.get('sessionPersistence')
    event = dict(type='user/message', seq=0, time=2, surfaceOp='append', data=dict(id='prior-message', role='user',
                 content=[dict(type='text', text='durable needle payload')], source=dict(kind='user')))
    handle = None
    try:
        for identity, workspace in [('prior', '/work'), ('hidden', '/outside')]:
            await storage.create(SessionHeader(identity, created_at=1, cwd=workspace))
            await storage.append(identity, [event])
        handle = await context.get('agent_loop').create_agent('caller', meta=dict(cwd='/work'))
        handle.agent.followup('Find the prior needle and read its exact event.')
        await handle.agent.when_idle()
        assert len(adapter.requests) == 6
        expected = {'session_search', 'session_event_search', 'session_trace', 'session_event_trace', 'session_event_read'}
        assert expected <= {schema['name'] for schema in adapter.requests[0]['tools']}
        results = [item for item in handle.agent.session.events if item['type'] == 'tool/result']
        assert len(results) == 5
        observed = json.dumps(results)
        assert 'durable needle payload' in observed and 'hidden' not in observed
        assert 'Target event seq 0' in json.dumps(adapter.requests[-1])
        await handle.agent.session.flush()
    finally:
        if handle is not None:
            await handle.dispose()
        first['shutdown'].shutdown(0)
        await first['shutdown'].wait()
    second = await run_profile(options)
    fresh = second['ctx']
    assert fresh.get('sessions').get('prior') is None
    assert fresh.get('sessions').get('caller') is None
    continuation = StrictMockLlmAdapter([dict(text='Recovered durable needle payload.')])
    fresh.provide('llm', continuation)
    restored = await fresh.get('agent_loop').resume('caller')
    try:
        invocation = ToolExecutionInput('restart', 'session_search', dict(query='needle'), agent=restored.agent,
                                       signal=AbortController().signal)
        result = await fresh.get('tools').execute(invocation)
        assert not result.is_error and 'durable needle payload' in result.value and 'hidden' not in result.value
        assert fresh.get('sessions').get('prior') is None
        restored.agent.followup('What did the exact read find?')
        await restored.agent.when_idle()
        assert 'durable needle payload' in json.dumps(continuation.requests)
    finally:
        await restored.dispose()
        second['shutdown'].shutdown(0)
        await second['shutdown'].wait()
