"""Real profile/Loader/core plugins/JSONL recovery, with only the LLM mocked."""
import json
from pathlib import Path
import pytest
import yaml
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import run_profile
from dsh.llm.message import create_user_message
from dsh.core.agent import AgentOptions
from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter

@pytest.mark.asyncio
async def test_profile_tool_turn_persists_and_resumes_after_shutdown(tmp_path):
    profile = tmp_path / 'profiles' / 'spine'
    init_profile(str(profile), [])
    rows = [{'id':name, 'name':'@deepseek-ai/dsh-' + name} for name in
            ['session', 'session-projection', 'tools', 'tool-executor-native', 'system-prompt', 'agent', 'agent-loop']]
    rows.append(dict(id='test-llm', name=str(Path(__file__).with_name('profile_llm_fixture.py')) + ':plugin'))
    rows.append({'id':'session-persistence-jsonl', 'name':'@deepseek-ai/dsh-session-persistence-jsonl',
                 'config':{'root':str(tmp_path / 'sessions')}})
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert':rows}]), encoding='utf-8')
    options = {'profile':'spine', 'dsh_home':str(tmp_path), 'wait_for_exit':False}
    first = await run_profile(options)
    ctx = first['ctx']
    adapter = StrictMockLlmAdapter([
        {'tool_calls':[{'id':'calc','name':'multiply','arguments':{'a':6,'b':7}}]},
        {'text':'The result is 42.'},
    ])
    ctx.get('llm').responses.extend(adapter.responses)
    adapter = ctx.get('llm')
    ctx.get('tools').register_tool(name='multiply', description='Multiply', parameters={'type':'object'},
                                   handler=lambda args: str(args['a'] * args['b']))
    model = AgentOptions(provider=adapter.provider, model=adapter.model)
    handle = await ctx.get('agent_loop').create_agent('profile-recovery', options=model, meta={'cwd':str(tmp_path)})
    try:
        handle.agent.followup(create_user_message(dict(content=[dict(type='text', text='Compute 6 * 7')], source=dict(kind='user'))))
        await handle.agent.when_idle()
        assert len(adapter.requests) == 2, handle.agent.session.events
        events = handle.agent.session.events
        assert any(e['type'] == 'tool/result' for e in events)
        assert '42' in json.dumps(events)
        await handle.agent.session.flush()
        reader = await ctx.get('sessionPersistence').open('profile-recovery', 'read')
        try:
            saved = await reader.read()
            assert reader.header['version'] == 4
            assert any(e['type'] == 'tool/result' for e in saved['events'])
        finally:
            await reader.close()
    finally:
        await handle.dispose()
        first['shutdown'].shutdown(0)
        await first['shutdown'].wait()
    assert list((tmp_path / 'sessions').rglob('*.jsonl.zstd'))
    second = await run_profile(options)
    fresh = second['ctx']
    assert fresh is not ctx
    assert fresh.get('sessions').get('profile-recovery') is None
    continuation = StrictMockLlmAdapter([{'text':'Recovered the previous answer: 42.'}])
    fresh.get('llm').responses.extend(continuation.responses)
    continuation = fresh.get('llm')
    restored = await fresh.get('agent_loop').resume('profile-recovery', options=model)
    try:
        assert any(e['type'] == 'tool/result' for e in restored.agent.session.events)
        restored.agent.followup(create_user_message(dict(content=[dict(type='text', text='What was the result?')], source=dict(kind='user'))))
        await restored.agent.when_idle()
        assert '42' in json.dumps(continuation.requests)
        await restored.agent.session.flush()
    finally:
        await restored.dispose()
        second['shutdown'].shutdown(0)
        await second['shutdown'].wait()
