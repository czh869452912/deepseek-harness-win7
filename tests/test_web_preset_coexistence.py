"""A single Web host must support multiple distinct standing preset trees."""
import pytest
import json

from canonical_web_fixture import web_context, close_web_context
from dsh.core.abort import NEVER_ABORTED
from dsh.core.scope import scope_of
from dsh.cordis.utils import Symbols
from dsh.llm.message import create_assistant_message


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
        registry = ctx.get('agentPresets')
        engines = [registry.serviceFor(agents[p], 'workflowEngine') for p in ('standard', 'cordis')]
        assert all(engine is not None for engine in engines)
        assert len({id(getattr(engine, '_original', engine)) for engine in engines}) == 2
        assert registry.serviceFor(agents['ptc'], 'workflowEngine') is None
        assert ctx.get('workflowEngine') is None
        tools = ctx.get('tools')
        async def model_tools(agent):
            assembly = await ctx.get('systemPrompt').assemble(dict(agent=agent, scope=scope_of(agent.ctx)))
            return [schema['name'] for schema in assembly['tools']]
        assert await model_tools(agents['ptc']) == ['run_code']
        assert 'run_code' not in await model_tools(agents['standard'])
        cordis_tools = await model_tools(agents['cordis'])
        assert {'cordis_inspect_list', 'cordis_inspect_query'} <= set(cordis_tools)
        assert 'cordis_define' not in cordis_tools
        fixture = tmp_path / 'ptc-input.txt'
        fixture.write_text('PTC nested dispatch works', encoding='utf-8')
        agents['ptc'].session.append('turn/start', dict(turn=1))
        agents['ptc'].session.append('step/start', dict(turn=1, step=1))
        advertised = dict(type='tool-call', id='ptc-code', name='run_code', arguments=json.dumps(dict(
            code='return await tools.read(%s)' % repr({'file_path': str(fixture)}),
            description='Verify preset scoped tool dispatch')))
        agents['ptc'].session.append('assistant/message', dict(turn=1, step=1,
            message=create_assistant_message(dict(source=dict(provider='fixture', model='fixture'),
                                                  content=[advertised]))), surface_op='append')
        batch = await tools.execute(dict(agent=agents['ptc'], signal=NEVER_ABORTED,
            calls=[advertised], log=dict(turn=1, step=1)))
        result = batch['results'][0]['result']
        assert not result.is_error, result.content
        agents['ptc'].session.append('step/end', dict(turn=1, step=1))
        agents['ptc'].session.append('turn/end', dict(turn=1, reason=dict(kind='completed')))
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
            selected = registry.inspectCompositions(agents['minimal'].ctx)
            existing = registry.inspectCompositions(agents[preset].ctx)
            assert len(selected) == len(existing) == 1
            assert selected[0]['id'] == existing[0]['id'] == preset
            selected_engine = registry.serviceFor(agents['minimal'], 'workflowEngine')
            existing_engine = registry.serviceFor(agents[preset], 'workflowEngine')
            assert getattr(selected_engine, Symbols.original, selected_engine) is getattr(existing_engine, Symbols.original, existing_engine)
        assert await model_tools(agents['ptc']) == ['run_code']
    finally:
        await close_web_context(ctx)
    reader = await persistence.open('coexist-ptc', 'read')
    try:
        restored = [event for event in (await reader.read())['events']
                    if event['type'].startswith('tool/ptc-dispatch')]
        assert restored == dispatch_events
    finally:
        await reader.close()

