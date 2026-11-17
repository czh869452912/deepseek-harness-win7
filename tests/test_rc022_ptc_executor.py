import asyncio
import pytest

from scripts.rc022_ptc_executor_probe import observe


@pytest.mark.asyncio
async def test_selected_executor_transport_controls_cancellation_and_owned_release():
    rows = {row['action']:row for row in await asyncio.wait_for(observe(), 30)}
    assert rows['python-schema']['model']['knownNames'] == ['run_code']
    assert 'class WorkArgs(TypedDict)' in rows['python-schema']['sdk']
    assert 'interface ToolArgsMap' in rows['typescript-schema']['sdk']
    assert rows['direct']['results'][0]['error']['info']['code'] == 'UNKNOWN_TOOL'
    assert rows['agent']['results'][0]['value'] == dict(logs=['log'], result=dict(n=6))
    assert rows['agent']['bodies'] == [dict(schema='work',parent=True,admitted=False,n=3)]
    assert rows['admission']['bodies'][0]['admitted']
    assert rows['null']['results'][0]['value'] == dict(logs=[], result=None)
    for action in ('caller-abort','retained-abort'):
        assert rows[action]['results'][0]['error']['info'] == dict(name='AbortError',code='ABORTED')
    assert rows['limit']['results'][0]['error']['info']['code'] == 'CODE_RUN_FAILED'
    assert not rows['limit']['bodies']
    assert rows['reset-unsupported']['reset']['code'] == 'CODE_RESET_FAILED'
    assert rows['reset']['notices'] == ['Program environment reset; retained variables cleared. Completed tool effects remain.']
    assert rows['reset-fails']['reset']['code'] == 'CODE_RESET_FAILED'
    assert rows['release-once']['releases'] == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize('structured',[False,True])
async def test_actual_selected_plugin_python_process_and_v4_session_log(tmp_path,structured):
    import json
    from types import SimpleNamespace
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.session.current_session import CurrentSession
    from dsh.core.tool_executor_ptc import PtcToolExecutorPlugin
    from dsh.code_runtime.ptc import PythonPtcRuntime
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(CurrentToolsPlugin)
    await ctx.plugin(PythonPtcRuntime)
    ctx.set_service('workingDirectory', SimpleNamespace(ensure=lambda agent,signal: str(tmp_path)))
    fiber = await ctx.plugin(PtcToolExecutorPlugin)
    session = CurrentSession.create('ptc-live', format_version=4)
    agent = SimpleNamespace(ctx=ctx, session=session)
    active = peak = 0
    original_results=[]
    async def work(args, execution):
        nonlocal active, peak
        assert execution.schema['name'] == 'work'
        assert execution.parent is not None
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.03)
            if structured:
                value=dict(n=args['n']*2,items=[args['n']]);original_results.append(value);return value
            return args['n'] * 2
        finally:
            active -= 1
    ctx.tools.register(dict(name='work', description='Work', parameters=dict(type='object',
        properties=dict(n=dict(type='integer')), required=['n']), execute=work, isConcurrencySafe=lambda args: True,
        output=dict(schema=(dict(type='object',properties=dict(n=dict(type='number'),items=dict(type='array',items=dict(type='integer'))),required=['n','items']) if structured else dict(type='number')), render=lambda args,value:[dict(type='text',text=str(value))])))
    program = "import asyncio\nvalues = await asyncio.gather(tools.work({'n': 1}), tools.work({'n': 2}))\nreturn sum(values)"
    if structured:program="import asyncio\nvalues = await asyncio.gather(tools.work({'n': 1}), tools.work({'n': 2}))\nvalues[0]['items'].append(99)\nreturn sum(value['n'] for value in values)"
    try:
        result = await ctx.tools.execute(dict(agent=agent, calls=[dict(type='tool-call', id='outer', name='run_code',
            arguments=json.dumps(dict(code=program,description='Run two calculations')))], signal=AbortController().signal,
            log=dict(turn=1,step=1)))
        value = result['results'][0]['result']
        assert not value.is_error, value.error
        assert value.value == dict(logs=[],result=6)
        assert peak == 2 and active == 0
        if structured:assert sorted(value['items'] for value in original_results)==[[1],[2]]
        types = [event['type'] for event in session.events]
        assert types[0] == 'tool/call' and types[-1] == 'tool/result'
        assert types.count('tool/ptc-dispatch-start') == types.count('tool/ptc-dispatch') == 2
        await fiber.dispose()
        assert not ctx.get('ptcRuntime').runs
    finally:
        await ctx.fiber.dispose()
