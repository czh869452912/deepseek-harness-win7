import asyncio
import json
from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.tool_calls import execute_tool_calls
from dsh.core.tools import ToolsPlugin, ToolExecutionResult


async def observe_prefix(implementation, action):
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(AgentLoopPlugin)
    handle = await ctx.get('agents').create(session_id=implementation + '-' + action)
    agent = handle.agent
    signal = asyncio.Event()
    prefixes, preparations = [], []
    first_entered, failure_entered = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    releases = {identity: loop.create_future() for identity in ('c1', 'c2', 'c3')}
    failure = RuntimeError('prefix failure')
    second_parallel = True
    terminal = None

    def enter(identity):
        nonlocal second_parallel
        prefixes.append(identity)
        if identity == 'c1':
            if action == 'abort':
                signal.set()
            if action == 'reclassify':
                second_parallel = False
            first_entered.set()
        if identity == 'c2' and action == 'throw':
            failure_entered.set()
            raise failure

    async def execute(arguments, execution):
        enter(arguments['identity'])
        return await releases[arguments['identity']]

    def pre(execution, next_fn):
        preparations.append(dict(callId=execution.call_id, prefixes=list(prefixes)))
        return next_fn()

    tools = ctx.get('tools')
    tools.register(dict(name='probe', description='probe',
        parameters=dict(type='object', properties=dict(identity=dict(type='string')), required=['identity']),
        isConcurrencySafe=lambda arguments: arguments['identity'] != 'c2' or second_parallel,
        execute=execute, output=dict(schema=dict(type='string'), render=lambda arguments, value: [dict(type='text', text=value)])))
    ctx.on('tools/pre-execute', pre)
    if implementation == 'custom-future':
        def dispatch(execution):
            enter(execution.call_id)
            return releases[execution.call_id]
        tools.dispatch = dispatch

    async def schedule():
        nonlocal terminal
        try:
            return await execute_tool_calls(agent.ctx, agent, 1, 1, [
                dict(type='tool-call', id=identity, name='probe', arguments=json.dumps(dict(identity=identity)))
                for identity in ('c1', 'c2', 'c3')], signal, max_parallel=3)
        except Exception as error:
            terminal = dict(message=str(error), sameFailure=error is failure)
            return None

    pending = asyncio.create_task(schedule())
    try:
        await asyncio.wait_for(first_entered.wait(), 5)
        if action == 'throw':
            await asyncio.wait_for(failure_entered.wait(), 5)
        held = dict(settled=pending.done())
        for identity, release in releases.items():
            release.set_result(dict(kind='final-result', result=ToolExecutionResult.from_raw(identity))
                if implementation == 'custom-future' else identity)
        result = await asyncio.wait_for(pending, 5)
        events = agent.session.events
        return dict(name=implementation + '-' + action, prefixes=prefixes, preparations=preparations,
            held=held, terminal=terminal, result=result,
            calls=[event['data']['callId'] for event in events if event['type'] == 'tool/call'],
            results=[dict(callId=event['data']['message']['source']['callId'],
                isError=event['data']['message']['content'][0]['isError'], code=event['data'].get('error', {}).get('code'))
                for event in events if event['type'] == 'tool/result'])
    finally:
        for release in releases.values():
            if not release.done():
                release.set_result(None)
        await asyncio.gather(pending, return_exceptions=True)
        await handle.dispose()
        await ctx.fiber.dispose()


async def observe_prefixes():
    observations = []
    for implementation in ('custom-future', 'canonical-body'):
        for action in ('none', 'abort', 'reclassify', 'throw'):
            observations.append(await observe_prefix(implementation, action))
    return observations
