import asyncio
import math
import os
import uuid

from dsh.acp.rpc import AcpRpc
from dsh.cordis.errors import AggregateError
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.abort import AbortController
from dsh.subprocess.types import SubprocessSpawnSpec, SubprocessStdio


DEFAULT_DISPOSE_EOF_GRACE_MS = 6000
DEFAULT_DISPOSE_GRACE_MS = 3000
MAX_TIMER_DELAY_MS = 2147483647
TOOL_KINDS = frozenset(('read', 'edit', 'delete', 'move', 'search', 'execute',
                        'think', 'fetch', 'switch_mode', 'other'))
CONFIG = Schema.object({
    'providerName': Schema.string().default('acp'),
    'command': Schema.string().required(),
    'args': Schema.array(Schema.string()).default([]),
    'cwd': Schema.string(),
    'permission': Schema.union(['allow', 'reject']).default('reject'),
    'env': Schema.dict(Schema.string()).default({}),
    'disposeEofGraceMs': Schema.number().default(DEFAULT_DISPOSE_EOF_GRACE_MS),
    'disposeGraceMs': Schema.number().default(DEFAULT_DISPOSE_GRACE_MS),
})


def failure_diagnostic(stage, category, outcome=None, stop_reason=None):
    fields = ['provider: ACP', 'stage: ' + stage, 'category: ' + category]
    if stop_reason is not None:
        fields.append('stop reason: ' + stop_reason)
    if outcome is not None:
        if outcome.exitCode is not None:
            fields.append('exit code: ' + str(outcome.exitCode))
        if outcome.signal is not None:
            fields.append('signal: ' + outcome.signal)
    return 'Subagent failure (' + '; '.join(fields) + ')'


class AcpRunFailure(RuntimeError):
    name = 'AcpRunFailure'

    def __init__(self, stage, category, cause, outcome=None):
        super().__init__('subagent-acp: ' + failure_diagnostic(stage, category, outcome))
        self.cause = cause
        self.__cause__ = cause


def acp_stop_reason(reason):
    return {'end_turn': 'completed', 'max_tokens': 'max-tokens',
            'refusal': 'refusal', 'cancelled': 'aborted'}.get(reason, 'error')


def to_acp_prompt(prompt):
    return [{'type': 'text', 'text': block['text']} for block in prompt if block['type'] == 'text']


def assert_usable_cwd(label, cwd):
    if not os.path.isabs(cwd):
        raise RuntimeError('subagent-acp: ' + label + ' must be an absolute path: ' + cwd)
    if not os.path.isdir(cwd) or not os.access(cwd, os.X_OK):
        raise RuntimeError('subagent-acp: ' + label + ' is not an accessible directory: ' + cwd)
    return cwd


def observe(future):
    if not future.cancelled():
        future.exception()


class AcpRun:
    localAgent = None

    def __init__(self, child, request, config, on_error):
        self.id = str(uuid.uuid4())
        self.child, self.request, self.config, self.on_error = child, request, config, on_error
        self.cancelled, self.remote_session_id = False, None
        self.cancel_settled = asyncio.get_running_loop().create_future()
        self.partial, self.permission = [], None
        self.disposal, self.result = None, None
        self.abort_listener = self.abort
        self.rpc = AcpRpc(self.write)
        self.rpc.notifications['session/update'] = self.update
        self.rpc.handlers['session/request_permission'] = self.request_permission
        self.reader = asyncio.create_task(self.read())
        self.reader.add_done_callback(observe)
        self.child.done.add_done_callback(observe)
        self.request['signal'].addEventListener('abort', self.abort_listener, {'once': True})
        if self.request['signal'].aborted:
            self.request_cancel()

    def report(self, error):
        try:
            self.on_error(error, 'error')
        except Exception:
            pass

    async def write(self, content):
        loop = asyncio.get_running_loop()
        def write_bytes():
            self.child.stdin.write(content.encode('utf-8'))
            self.child.stdin.flush()
        await loop.run_in_executor(None, write_bytes)

    async def read(self):
        loop = asyncio.get_running_loop()
        try:
            while True:
                chunk = await loop.run_in_executor(None, self.child.stdout.read1, 4096)
                if not chunk:
                    self.rpc.end()
                    return
                self.rpc.data(chunk)
        except Exception as error:
            self.rpc.close(error)

    def update(self, params):
        update = params['update']
        if update.get('sessionUpdate') == 'agent_message_chunk':
            content = update['content']
            if content.get('type') == 'text' and content['text']:
                self.partial.append(content['text'])

    def request_permission(self, params, signal):
        policy = self.config['permission']
        kind = params['toolCall'].get('kind')
        kind = kind if kind in TOOL_KINDS else 'unknown'
        if policy == 'allow':
            for option in params['options']:
                if option.get('kind') in ('allow_once', 'allow_always'):
                    self.permission = (policy, kind, 'allowed')
                    return {'outcome': {'outcome': 'selected', 'optionId': option['optionId']}}
        self.permission = (policy, kind, 'denied')
        return {'outcome': {'outcome': 'cancelled'}}

    def permission_diagnostic(self):
        if self.permission is None:
            return None
        policy, kind, decision = self.permission
        return 'ACP unattended decision (policy: {}; request: {}; decision: {})'.format(policy, kind, decision)

    def output(self):
        text = ''.join(self.partial)
        return [{'type': 'text', 'text': text}] if text else []

    def abort(self, event):
        self.request_cancel()

    def detach(self):
        self.request['signal'].removeEventListener('abort', self.abort_listener)

    def request_cancel(self):
        if self.cancelled:
            return
        self.cancelled = True
        self.cancel_settled.set_result(None)
        if self.remote_session_id is not None and not self.rpc.closed:
            self.rpc.spawn(self.rpc.notify('session/cancel', {'sessionId': self.remote_session_id}))

    async def race_cancel(self, operation):
        pending = asyncio.ensure_future(operation)
        pending.add_done_callback(observe)
        completed, _pending = await asyncio.wait([pending, self.cancel_settled], return_when=asyncio.FIRST_COMPLETED)
        if self.cancel_settled in completed:
            raise RuntimeError('subagent cancelled while the ACP operation was running')
        return await pending

    async def observe_outcome(self):
        if self.child.done.done():
            try:
                return self.child.done.result()
            except Exception:
                return None
        bound = asyncio.create_task(self.request['signal'].wait_aborted())
        try:
            completed, _pending = await asyncio.wait([self.child.done, bound],
                timeout=math.ceil(self.config['disposeGraceMs']) / 1000.0,
                return_when=asyncio.FIRST_COMPLETED)
            if self.child.done in completed:
                try:
                    return self.child.done.result()
                except Exception:
                    return None
            return None
        finally:
            bound.cancel()
            await asyncio.gather(bound, return_exceptions=True)

    async def initialize(self, cwd):
        stage = 'initialize'
        try:
            await self.race_cancel(self.rpc.request('initialize', {'protocolVersion': 1, 'clientCapabilities': {}}))
            stage = 'new-session'
            session = await self.race_cancel(self.rpc.request('session/new', {'cwd': cwd, 'mcpServers': []}))
            if not isinstance(session, dict) or not isinstance(session.get('sessionId'), str):
                raise AcpRunFailure('new-session', 'protocol', RuntimeError('ACP child published without a session id'))
            self.remote_session_id = session['sessionId']
            if self.cancelled:
                raise RuntimeError('subagent cancelled before the ACP session started')
        except BaseException as error:
            self.detach()
            if isinstance(error, asyncio.CancelledError):
                self.request_cancel()
            cancelled = self.cancelled
            outcome = None if cancelled else await self.observe_outcome()
            failure = error if isinstance(error, AcpRunFailure) else AcpRunFailure(stage,
                'transport' if outcome is None else 'process-exit', error, outcome)
            if not cancelled:
                self.report(getattr(error, 'cause', error))
            try:
                await self.dispose_process()
            except Exception as cleanup_error:
                self.report(cleanup_error)
                cleanup = AcpRunFailure('teardown', 'unknown' if outcome is None else 'process-exit', cleanup_error, outcome)
                if cancelled:
                    raise AggregateError([cleanup], str(cleanup))
                raise AggregateError([failure, cleanup], str(failure) + '; ' + str(cleanup))
            if isinstance(error, asyncio.CancelledError):
                raise
            if cancelled:
                raise RuntimeError('subagent request was aborted before the ACP child started')
            raise failure
        self.result = asyncio.create_task(self.drive())
        self.result.add_done_callback(observe)
        return self

    async def drive(self):
        diagnostic = None
        try:
            response = await self.race_cancel(self.rpc.request('session/prompt',
                {'sessionId': self.remote_session_id, 'prompt': to_acp_prompt(self.request['prompt'])}))
            reason = response['stopReason']
            stop_reason = acp_stop_reason(reason)
            if reason == 'max_turn_requests':
                diagnostic = failure_diagnostic('prompt', 'remote-limit', stop_reason=reason)
            elif reason not in ('end_turn', 'max_tokens', 'refusal', 'cancelled'):
                diagnostic = failure_diagnostic('prompt', 'unknown', stop_reason='unknown')
            permission = self.permission_diagnostic()
            if reason != 'end_turn' and permission is not None:
                diagnostic = permission if diagnostic is None else diagnostic + '\n' + permission
        except Exception as error:
            if self.cancelled:
                return {'output': self.output(), 'stopReason': 'aborted'}
            outcome = await self.observe_outcome()
            if self.cancelled:
                return {'output': self.output(), 'stopReason': 'aborted'}
            diagnostic = failure_diagnostic('prompt' if outcome is None else 'process',
                'transport' if outcome is None else 'process-exit', outcome)
            permission = self.permission_diagnostic()
            if permission is not None:
                diagnostic += '\n' + permission
            self.report(error)
            stop_reason = 'error'
        finally:
            self.detach()
        if self.cancelled:
            return {'output': self.output(), 'stopReason': 'aborted'}
        result = {'output': self.output(), 'stopReason': stop_reason}
        if diagnostic is not None:
            result['diagnostic'] = diagnostic
        return result

    async def teardown(self):
        controller = AbortController()
        timer = asyncio.get_running_loop().call_later(self.config['disposeEofGraceMs'] / 1000.0, controller.abort)
        try:
            if self.child.stdin is not None and not self.child.stdin.closed:
                self.child.stdin.close()
            if not await self.child.wait_for_exit(controller.signal):
                self.child.terminate()
                await self.child.wait_for_exit()
            await self.child.done
            await self.reader
            self.rpc.close()
            await self.rpc.drain()
            if self.child.stdout is not None:
                self.child.stdout.close()
        finally:
            timer.cancel()

    async def dispose_process(self):
        if self.disposal is None:
            self.disposal = asyncio.create_task(self.teardown())
            self.disposal.add_done_callback(observe)
        await asyncio.shield(self.disposal)

    async def dispose(self):
        self.detach()
        self.request_cancel()
        try:
            await self.dispose_process()
        except Exception as error:
            self.report(error)
            outcome = await self.observe_outcome()
            raise AcpRunFailure('teardown', 'unknown' if outcome is None else 'process-exit', error, outcome)


class AcpProvider:
    capabilities = {'agentOptions': False, 'outputSchema': False, 'depthLimit': False, 'toolFilter': False, 'persona': False}
    inheritsParentContext = False

    def __init__(self, ctx, config):
        self.ctx, self.config, self.name = ctx, config, config['providerName']

    def report(self, error, reason):
        logger = self.ctx.get('logger')
        if logger is not None:
            logger.warn('subagent-acp "{}": child run failed ({}): {}'.format(self.name, reason, str(error)))

    async def start(self, request):
        if request['signal'].aborted:
            raise RuntimeError('subagent request was aborted before the ACP child started')
        try:
            cwd = self.config.get('cwd')
            if cwd is None:
                header = request['parent'].session.header
                cwd = header.get('cwd') if isinstance(header, dict) else getattr(header, 'cwd', None)
                if cwd is None:
                    raise RuntimeError('subagent-acp: no working directory for the child — configure `cwd` or delegate from a parent session that has one')
                cwd = assert_usable_cwd('parent session cwd', cwd)
        except Exception as error:
            self.report(error, 'error')
            raise AcpRunFailure('initialize', 'configuration', error)
        spec = SubprocessSpawnSpec([self.config['command']] + self.config['args'], cwd,
            SubprocessStdio('pipe', 'pipe', 'inherit'), self.config['disposeGraceMs'], env=self.config['env'])
        try:
            child = self.ctx.get('subprocess').spawn(spec)
            if child.pid <= 0:
                await child.done
        except Exception as error:
            try:
                self.report(error, 'error')
            except Exception:
                pass
            raise AcpRunFailure('process', 'process-start', error)
        return await AcpRun(child, request, self.config, self.report).initialize(cwd)


class SubagentAcp(Plugin):
    id = 'subagent-acp'
    inject = ['subagents', 'subprocess']
    Config = CONFIG

    def apply(self, ctx):
        config = dict(self.config)
        for field in ('disposeEofGraceMs', 'disposeGraceMs'):
            value = config[field]
            if not math.isfinite(value) or value <= 0 or value > MAX_TIMER_DELAY_MS:
                raise RuntimeError('subagent-acp: {} must be a positive finite number no greater than {}'.format(field, MAX_TIMER_DELAY_MS))
        if config.get('cwd') == '':
            raise RuntimeError('subagent-acp: config cwd must not be empty — omit the key to inherit the parent session cwd')
        if 'cwd' in config:
            config['cwd'] = assert_usable_cwd('config cwd', os.path.abspath(config['cwd']))
        ctx.get('subagents').registerProvider(AcpProvider(ctx, config))
