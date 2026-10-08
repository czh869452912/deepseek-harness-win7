import asyncio
import builtins
import copy
import json

from dsh.cordis.plugin import Plugin


class FixturePlugin(Plugin):
    id = 'web-journey-fixture'
    inject = ['llm', 'sessions']

    def apply(self, ctx):
        record = getattr(builtins, '__web_journey_probe')
        ctx.on('session/event', lambda session, event: record['events'].append(
            dict(sessionId=session.id, event=copy.deepcopy(event))))

        class Adapter:
            def __init__(self):
                self.calls = {}

            async def list_models(self, provider):
                return [dict(id='fixture', name='Controlled local browser journey')]

            async def resolve_model(self, provider, model, signal=None):
                record['lookups'].append(dict(provider=provider, id=model))
                return dict(provider=provider, id=model, name=model,
                    context=dict(contextWindow=128000), defaultMaxTokens=4096)

            async def stream(self, options):
                signal = options.get('signal')
                request = {name: copy.deepcopy(value) for name, value in options.items() if name != 'signal'}
                record['requests'].append(dict(request=request, signalPresent=signal is not None,
                    signalAborted=getattr(signal, 'aborted', False)))
                if options.get('purpose') == 'session-title':
                    text = 'Controlled browser journey'
                else:
                    user = next(message for message in reversed(options['messages']) if message['role'] == 'user'
                        and any(block['type'] == 'text' and block['text'].strip() in ('WEB_TOOL', 'WEB_QUESTION',
                            'WEB_APPROVAL', 'WEB_CANCEL', 'WEB_CORDIS', 'WEB_REOPEN') for block in message['content']))
                    prompt = ''.join(block['text'] for block in user['content'] if block['type'] == 'text')
                    scenario = next(name for name in ('WEB_TOOL', 'WEB_QUESTION', 'WEB_APPROVAL',
                        'WEB_CANCEL', 'WEB_CORDIS', 'WEB_REOPEN') if name in prompt)
                    call = self.calls.get(user['id'], 0) + 1
                    self.calls[user['id']] = call
                    if scenario == 'WEB_CANCEL':
                        yield dict(type='block-start', index=0, blockType='text')
                        yield dict(type='text-delta', index=0, text='WEB_CANCEL_WAITING')
                        future = asyncio.get_running_loop().create_future()

                        def aborted(event):
                            if not future.done():
                                future.set_result(None)

                        trace = dict(scenario=scenario, attached=1, detached=0, aborted=False)
                        record['cancellation'].append(trace)
                        signal.addEventListener('abort', aborted, dict(once=True))
                        try:
                            if not signal.aborted:
                                await future
                            trace['aborted'] = bool(signal.aborted)
                            signal.throwIfAborted()
                            raise RuntimeError('Cancellation fixture resumed without an abort')
                        finally:
                            trace['finallyAborted'] = bool(signal.aborted)
                            record['diagnostics'].append(dict(scenario=scenario, futureCancelled=future.cancelled()))
                            signal.removeEventListener('abort', aborted)
                            trace['detached'] = 1
                        return
                    if call == 1 or scenario == 'WEB_APPROVAL' and call == 2:
                        if scenario == 'WEB_QUESTION':
                            tool = 'ask_user_question'
                            arguments = dict(questions=[dict(id='browser-choice', question='Choose a local test result.',
                                options=[dict(label='Proceed', description='Continue the controlled journey.'),
                                    dict(label='Reject', description='Return a rejection.')])])
                        elif scenario == 'WEB_CORDIS':
                            tool, arguments = 'cordis_inspect_self', {}
                        else:
                            tool = 'pwsh'
                            command = 'Write-Output WEB_TOOL_ROUND_TRIP'
                            if scenario == 'WEB_APPROVAL':
                                escaped = record['approvalArtifact'].replace("'", "''")
                                command = "Set-Content -LiteralPath '" + escaped + "' -Value WEB_APPROVAL_ROUND_TRIP; Get-Content -LiteralPath '" + escaped + "'"
                            arguments = dict(command=command, description='Run the controlled local browser tool.')
                            if scenario == 'WEB_APPROVAL' and call == 2:
                                arguments.update(sandbox_permissions='danger-full-access',
                                    justification='Allow this exact controlled write to the isolated test home.')
                        arguments_text = json.dumps(arguments, separators=(',', ':'))
                        call_id = scenario.lower() + '-call-' + str(call)
                        yield dict(type='block-start', index=0, blockType='tool-call')
                        yield dict(type='tool-call-delta', index=0, id=call_id, name=tool, argumentsDelta=arguments_text)
                        yield dict(type='block-end', index=0, block=dict(type='tool-call', id=call_id,
                            name=tool, arguments=arguments_text))
                        yield dict(type='finish', reason=dict(kind='tool-calls'))
                        return
                    result = next(message for message in reversed(options['messages'])
                        if any(block['type'] == 'tool-result' for block in message['content']))
                    text = scenario + '_FINAL ' + ''.join(part['text'] for block in result['content']
                        if block['type'] == 'tool-result' for part in block['content'] if part['type'] == 'text')
                yield dict(type='block-start', index=0, blockType='text')
                yield dict(type='text-delta', index=0, text=text)
                yield dict(type='block-end', index=0, block=dict(type='text', text=text))
                yield dict(type='finish', reason=dict(kind='stop'))

        ctx.get('llm').register_adapter(['web-journey-fixture'], Adapter())
