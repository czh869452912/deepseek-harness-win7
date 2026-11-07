"""Ordinary Python failures through canonical activation, Remote and steering."""
import pytest

from canonical_web_fixture import web_context, close_web_context
from dsh.typert.dispatch import RemoteDispatcher


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True], ids=['sync', 'async'])
@pytest.mark.parametrize('phase', ['startup', 'rpc'])
@pytest.mark.parametrize('chain', ['none', 'implicit', 'explicit'])
async def test_native_python_traceback_reaches_diagnostics_and_model(tmp_path, phase, asynchronous, chain):
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='python-error', cwd=str(tmp_path), agentPreset='minimal'))
        owner = ctx.get('agents').get('python-error')
        messages = []
        original = owner.steer
        owner.steer = messages.append
        ctx.effect(lambda: lambda: setattr(owner, 'steer', original))
        runner, gateway = ctx.get('dynamicCordisRunner'), RemoteDispatcher(ctx)
        prefix = 'async ' if asynchronous else ''
        expression = '1 / 0' if phase == 'startup' else "1 / args['zero']"
        body = [expression]
        if chain != 'none':
            body = ['try:', "    raise ValueError('business cause')", 'except ValueError as cause:',
                    "    raise ZeroDivisionError('division by zero') from cause" if chain == 'explicit' else '    ' + expression]
        if phase == 'startup':
            source = prefix + 'def plugin(ctx):\n' + ''.join('    ' + statement + '\n' for statement in body)
            code, line = dict(host=source, client='return () => {}'), len(body) + 1
        else:
            source = ('def plugin(ctx):\n    ' + prefix + 'def divide(args):\n'
                      + ''.join('        ' + statement + '\n' for statement in body)
                      + "    harness.handle('divide', divide)\n")
            code, line = dict(host=source), len(body) + 2
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='error'),
            name='Python failure', purpose='Preserve real source diagnostics', code=code))
        pid, package = defined['pluginId'], defined['packageId']

        async def remote(remote_method, **args):
            return await gateway.invoke(dict(namespace='dynamicCordisRunner', method=remote_method, args=args))

        started = await runner.run(owner, pid, package, 'run')
        if phase == 'startup':
            request_id = runner.inventory()[0]['latestRun']['approvalRequestId']
            failure = await remote('runHostHalf', agentId=owner.id, pluginId=pid, packageId=package,
                mode='run', requestId=request_id, approveFutureVersions=False)
            assert not failure['ok']
            accepted = await remote('resolveRequestRun', requestId=request_id,
                resolution=dict(ok=False, reason='host-half-failed', message=failure['message'], stack=failure['stack']))
            assert accepted == dict(accepted=True)
            assert runner.inventory()[0]['latestRun']['error']['stack'] == failure['stack']
        else:
            assert started['ok']
            failure = await remote('invoke', pluginId=pid, pluginRunId=started['pluginRunId'], method='divide', args={'zero': 0})
            assert failure['code'] == 'handler-error'
            assert runner.inventory()[0]['latestRun']['status'] == 'running'
        assert failure['message'] == 'division by zero'
        stack = failure['stack']
        assert stack.startswith('Traceback (most recent call last):\n')
        assert 'File "<cordis-host>", line ' + str(line) in stack
        assert 'ZeroDivisionError: division by zero' in stack
        assert 'too many positional arguments' not in stack
        assert 'signature.bind' not in stack
        if chain == 'none':
            assert 'During handling of the above exception' not in stack
            assert 'The above exception was the direct cause' not in stack
        else:
            assert 'ValueError: business cause' in stack
            connector = ('The above exception was the direct cause' if chain == 'explicit'
                         else 'During handling of the above exception')
            assert connector in stack
            assert stack.count('Traceback (most recent call last):') == 2
        assert any(stack in message['content'][0]['text'] for message in messages)
    finally:
        await close_web_context(ctx)
