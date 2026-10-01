"""Observe native public services corresponding to approval.spec.ts."""
import asyncio
import re

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.scope import carrier_key_of
from dsh.core.session import Session, SessionStore
from dsh.core.system_prompt.service import SystemPrompt
from dsh.diagnostics.invariants import InvariantRegistry
from dsh.interaction.user_approval import UserApprovalPlugin
from dsh.interaction.approval_invariant import ApprovalInvariantPlugin


class AgentView:
    def __init__(self, session):
        self.session = session


def audit(session):
    events = [event for event in session.events if event['type'].startswith('approval/')]
    rows = []
    for index, event in enumerate(events):
        data = dict(event['data'])
        row = dict(type=event['type'], data=data)
        if 'id' in data:
            identity = data['id']
            data['id'] = '<uuid>'
            row.update(uuid=bool(re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', identity)),
                       paired=index == 0 or identity == events[0]['data']['id'])
        rows.append(row)
    return rows


async def drain():
    for _ in range(4):
        await asyncio.sleep(0)


async def observe():
    rows = []
    for mode in ['pre-aborted', 'never', 'abort-grant', 'abort-error', 'answer', 'missing']:
        ctx, controller = Context(), AbortController()
        await ctx.plugin(UserApprovalPlugin, {'policy': 'never' if mode == 'never' else 'ask'})
        session = Session('probe-' + mode)
        agent = AgentView(session)
        session.append('turn/start', {'turn': 1})
        request = dict(agent=agent, toolName='pwsh', signal=controller.signal)
        observed = dict(calls=0, borrowed=False, carrier=False)
        entered, answer = asyncio.get_running_loop().create_future(), asyncio.get_running_loop().create_future()

        async def answerer(req, next_fn, caller_ctx=None):
            observed.update(calls=observed['calls'] + 1, borrowed=req is request, carrier=carrier_key_of(caller_ctx) is agent)
            if mode.startswith('abort-'):
                entered.set_result(None)
                return await answer
            return 'allowed-once'

        if mode != 'missing':
            ctx.on('approval/request', answerer)
        if mode == 'pre-aborted':
            controller.abort(None)
        pending = asyncio.create_task(ctx.get('approval').request(request))
        try:
            if mode.startswith('abort-'):
                await asyncio.wait_for(entered, 1)
                controller.abort('cancelled')
            outcome = await asyncio.wait_for(pending, 1)
            before = audit(session)
            if mode == 'abort-grant':
                answer.set_result('allowed-once')
            if mode == 'abort-error':
                answer.set_exception(RuntimeError('late answer failed'))
            if mode == 'answer':
                controller.abort()
            await drain()
            rows.append(dict(mode=mode, outcome=outcome, before=before, after=audit(session), **observed))
        finally:
            if not answer.done():
                answer.set_result('rejected')
            await asyncio.gather(pending, return_exceptions=True)
            await ctx.fiber.dispose()
    ctx = Context()
    approval = await ctx.plugin(UserApprovalPlugin)
    prompt = await ctx.plugin(SystemPrompt)
    agent = AgentView(Session('prompt'))

    async def text():
        return [entry['text'] for entry in (await ctx.get('systemPrompt').assemble({'agent': agent}))['contexts'] if entry['name'] == 'approval:policy']

    first = await text()
    await prompt.dispose()
    await ctx.plugin(SystemPrompt)
    reloaded = await text()
    await approval.dispose()
    rows.append(dict(mode='prompt-lifecycle', first=first, reloaded=reloaded, disposed=await text(), serviceGone=ctx.get('approval') is None))
    await ctx.fiber.dispose()
    ctx = Context()
    await ctx.plugin(UserApprovalPlugin)
    agent, messages = AgentView(Session('policy')), []
    agent.inject = messages.append
    ctx.get('approval').setPolicy(agent, 'never')
    ctx.get('approval').setPolicy(agent, 'never')
    normalized = [dict(message, id='<message>', identified=isinstance(message.get('id'), str) and bool(message['id'])) for message in messages]
    rows.append(dict(mode='policy-notice', audit=audit(agent.session), messages=normalized))
    await ctx.fiber.dispose()
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(InvariantRegistry)
    await ctx.plugin(ApprovalInvariantPlugin)
    session = ctx.get('sessions').create('precommit')
    session.append('turn/start', {'turn': 1})

    def veto(_mode, name, args, *extra):
        if name == 'session/event' and args[1]['type'] == 'approval/asked':
            raise RuntimeError('later veto')

    remove = ctx.on('internal/dispatch', veto, global_listener=True)
    failure = ''
    try:
        session.append('approval/asked', dict(id='same', toolName='pwsh'))
    except Exception as error:
        failure = str(error)
    remove()
    session.append('approval/asked', dict(id='same', toolName='pwsh'))
    unmatched = ''
    try:
        session.append('approval/decided', dict(id='other', outcome='rejected'))
    except Exception as error:
        unmatched = str(error)
    session.append('approval/decided', dict(id='same', outcome='cancelled'))
    rows.append(dict(mode='invariant-veto', veto=failure, unmatched=unmatched,
                     events=[dict(type=event['type'], data=dict(event['data'])) for event in session.events]))
    await ctx.fiber.dispose()
    return rows
