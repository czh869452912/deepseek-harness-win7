"""A single Web host must support multiple distinct standing preset trees."""
import pytest
import json

from canonical_web_fixture import web_context, close_web_context
from dsh.core.tools import ToolExecutionInput
from dsh.core.abort import NEVER_ABORTED
from dsh.presets.mount import standing_mount_for, service_for_agent


@pytest.mark.asyncio
async def test_standard_ptc_and_cordis_coexist_and_execute(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    persistence = ctx.get('sessionPersistence')
    logged_dispatches = []
    def shape_dispatch(dispatch, next_fn):
        logged_dispatches.append(dispatch['name'])
        return [{'type': 'text', 'text': 'durable PTC preview'}]
    ctx.on('tools/ptc-dispatch-log', shape_dispatch)
    try:
        agents = {}
        for preset in ('standard', 'ptc', 'cordis', 'minimal'):
            await ctx.get('sessionController').create(dict(
                sessionId='coexist-' + preset, cwd=str(tmp_path), agentPreset=preset))
            agents[preset] = ctx.get('agents').get('coexist-' + preset)
        engines = [service_for_agent(ctx, agents[p], 'workflowEngine') for p in ('standard', 'ptc', 'cordis')]
        assert all(engine is not None for engine in engines)
        assert len({id(getattr(engine, '_original', engine)) for engine in engines}) == 3
        assert ctx.get('workflowEngine') is None
        tools = ctx.get('tools')
        assert [s['name'] for s in tools.schemas(agents['ptc'])] == ['run_code']
        assert 'run_code' not in [s['name'] for s in tools.schemas(agents['standard'])]
        assert 'cordis_define' in [s['name'] for s in tools.schemas(agents['cordis'])]
        fixture = tmp_path / 'ptc-input.txt'
        fixture.write_text('PTC nested dispatch works', encoding='utf-8')
        agents['ptc'].session.append('turn/start', dict(turn=1))
        result = await tools.execute(ToolExecutionInput('ptc-code', 'run_code',
            dict(code='return await tools.read(%s)' % repr({'file_path': str(fixture)}), description='Verify preset scoped tool dispatch'),
            agent=agents['ptc'], signal=NEVER_ABORTED))
        assert not result.is_error, result.content
        agents['ptc'].session.append('turn/end', dict(turn=1, stopReason='completed'))
        assert 'result' in result.value
        assert 'PTC nested dispatch works' in json.dumps(result.value)
        assert logged_dispatches == ['read']
        dispatch_events = [event for event in agents['ptc'].session.events
                           if event['type'].startswith('tool/ptc-dispatch')]
        assert [event['type'] for event in dispatch_events] == [
            'tool/ptc-dispatch-start', 'tool/ptc-dispatch']
        assert dispatch_events[1]['data']['content'] == [
            {'type': 'text', 'text': 'durable PTC preview'}]
        # Switching a never-started session reuses standing mounts without
        # changing the tools or isolated providers of other sessions.
        for preset in ('ptc', 'cordis', 'standard'):
            await ctx.get('agentPresets').select(agents['minimal'], preset)
            assert standing_mount_for(agents['minimal'].ctx) is standing_mount_for(agents[preset].ctx)
        assert [s['name'] for s in tools.schemas(agents['ptc'])] == ['run_code']
    finally:
        await close_web_context(ctx)
    reader = await persistence.open('coexist-ptc', 'read')
    try:
        restored = [event for event in (await reader.read())['events']
                    if event['type'].startswith('tool/ptc-dispatch')]
        assert restored == dispatch_events
    finally:
        await reader.close()

