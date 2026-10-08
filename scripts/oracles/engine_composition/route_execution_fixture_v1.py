import asyncio
import builtins
import copy
import json

from dsh.cordis.plugin import Plugin


class FixturePlugin(Plugin):
    id = 'route-execution-fixture'
    inject = ['llm', 'sessions']

    def apply(self, ctx):
        record = getattr(builtins, '__route_execution_probe')
        ctx.on('session/event', lambda session, event: record['events'].append(
            dict(sessionId=session.id, event=copy.deepcopy(event))))
        def created(payload):
            agent = payload['agent']
            options = agent.options.to_dict()
            if hasattr(agent.options, 'subagentDepth'):
                options['subagentDepth'] = agent.options.subagentDepth
            record['created'].append(dict(id=agent.id, header=agent.session.header.to_dict(), options=options))

        ctx.on('agent/created', created)
        ctx.on('agent/disposed', lambda payload: record['disposed'].append(payload['agent'].id))

        class Adapter:
            def __init__(self):
                self.calls = {}

            async def list_models(self, provider):
                return [dict(provider=provider, id=model, name=model) for model in ('parent', 'child')]

            async def resolve_model(self, provider, model, signal=None):
                record['lookups'].append(dict(provider=provider, id=model))
                return dict(provider=provider, id=model, name=model,
                    context=dict(contextWindow=128000), defaultMaxTokens=4096,
                    reasoning=dict(efforts=[dict(id='low', name='Low'), dict(id='high', name='High')],
                        defaultEffort='low' if provider == 'route-beta' else 'high'))

            async def stream(self, options):
                signal = options.get('signal')
                record['requests'].append(dict(request={name: copy.deepcopy(value) for name, value in options.items()
                    if name != 'signal'}, signalPresent=signal is not None,
                    signalAborted=bool(getattr(signal, 'aborted', False))))
                scenarios = ('WORKFLOW_MODEL', 'WORKFLOW_CANCEL', 'RALPH_ROUNDS')
                user = next(message for message in reversed(options['messages']) if message['role'] == 'user'
                    and any(block['type'] == 'text' and (block['text'] in scenarios or block['text'].startswith(('CHILD_', 'You are one fresh worker')))
                        for block in message['content']))
                prompt = ''.join(block['text'] for block in user['content'] if block['type'] == 'text')
                if options.get('purpose') == 'session-title':
                    text = 'Controlled route execution'
                elif prompt.startswith('You are one fresh worker'):
                    first = 'Ralph round: 1 of ' in prompt
                    value = dict(status='continue' if first else 'complete', summary='Controlled round report',
                        evidence=['Verified local fixture'], nextSteps=['Continue local work'] if first else [], blocker='')
                    encoded = json.dumps(value, separators=(',', ':'))
                    call_id = 'ralph-report-one' if first else 'ralph-report-two'
                    yield dict(type='block-start', index=0, blockType='tool-call')
                    yield dict(type='tool-call-delta', index=0, id=call_id, name='structured_output', argumentsDelta=encoded)
                    yield dict(type='block-end', index=0, block=dict(type='tool-call', id=call_id, name='structured_output', arguments=encoded))
                    yield dict(type='finish', reason=dict(kind='tool-calls'))
                    return
                elif prompt.startswith('CHILD_'):
                    if prompt == 'CHILD_CANCEL':
                        ready = asyncio.get_running_loop().create_future()
                        trace = dict(sessionId=options['sessionId'], attached=True, detached=False, aborted=False)
                        record['cancellation'].append(trace)
                        record['childStarted'].set()

                        def aborted(event):
                            if not ready.done():
                                ready.set_result(None)

                        signal.addEventListener('abort', aborted, dict(once=True))
                        try:
                            if not signal.aborted:
                                await ready
                            trace['aborted'] = bool(signal.aborted)
                            signal.throwIfAborted()
                            raise RuntimeError('Child cancellation did not abort')
                        finally:
                            signal.removeEventListener('abort', aborted)
                            trace['detached'] = True
                        return
                    text = 'CHILD_RESULT ' + options['provider'] + '/' + options['model']
                else:
                    call = self.calls.get(user['id'], 0) + 1
                    self.calls[user['id']] = call
                    if call == 1:
                        arguments = dict(description='Controlled route child', prompt='CHILD_' + prompt,
                            run_in_background=False)
                        tool = 'subagent_fork' if prompt == 'FORK_INHERIT' else 'subagent'
                        if prompt in ('SPAWN_CHANGE', 'SPAWN_EFFORT', 'CANCEL'):
                            arguments.update(provider='route-beta', model='child')
                        if prompt == 'SPAWN_EFFORT':
                            arguments['reasoning_effort'] = 'high'
                        if prompt == 'DENIED_ROUTE':
                            arguments.update(provider='outside', model='child')
                        if prompt == 'HALF_ROUTE':
                            arguments['model'] = 'child'
                        if prompt in ('WORKFLOW_MODEL', 'WORKFLOW_CANCEL'):
                            tool = 'workflow'
                            child = 'CHILD_CANCEL' if prompt == 'WORKFLOW_CANCEL' else 'CHILD_WORKFLOW_MODEL'
                            script = 'phase("Selected child"); const value = await agent(' + json.dumps(child) + ', {provider:"route-beta",model:"child",label:"selected-child",phase:"Selected child"}); return {child:value};'
                            arguments = dict(meta=dict(name='selected-child', description='Controlled canonical engine child'), script=script, args={})
                        elif prompt == 'RALPH_ROUNDS':
                            tool = 'ralph'
                            arguments = dict(objective='Complete controlled local rounds', maxRounds=2)
                        encoded = json.dumps(arguments, separators=(',', ':'))
                        identity = 'route-call-' + prompt.lower()
                        yield dict(type='block-start', index=0, blockType='tool-call')
                        yield dict(type='tool-call-delta', index=0, id=identity, name=tool, argumentsDelta=encoded)
                        yield dict(type='block-end', index=0,
                            block=dict(type='tool-call', id=identity, name=tool, arguments=encoded))
                        yield dict(type='finish', reason=dict(kind='tool-calls'))
                        return
                    text = 'PARENT_RESULT ' + prompt
                yield dict(type='block-start', index=0, blockType='text')
                yield dict(type='text-delta', index=0, text=text)
                yield dict(type='block-end', index=0, block=dict(type='text', text=text))
                yield dict(type='finish', reason=dict(kind='stop'))

        ctx.get('llm').register_adapter(['route-alpha', 'route-beta'], Adapter())
