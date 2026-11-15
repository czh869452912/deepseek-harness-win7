"""rc.3 ACP provider using captured cwd and shared external-run contracts."""
import asyncio
import math
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.errors import AggregateError
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.session.json import UNDEFINED
from dsh.subprocess.types import SubprocessSpawnSpec, SubprocessStdio
from .acp import AcpRunFailure, acp_stop_reason, failure_diagnostic, to_acp_prompt, observe, MAX_TIMER_DELAY_MS
from .acp_current import CurrentAcpRun
from .assistant_output_current import AssistantOutputFold
from .out_of_process import NO_START_CAPABILITIES, assert_usable_cwd, settle_run_result


class CandidateAcpRun(CurrentAcpRun):
    def __init__(self, *args):
        self.fold = AssistantOutputFold()
        super().__init__(*args)

    def output(self):
        return self.fold.collect() or []

    def update(self, params):
        update = params['update']
        if update.get('sessionUpdate') == 'agent_message_chunk':
            content = update['content']
            if content.get('type') == 'text':
                self.fold.pushText(content['text'])

    async def initialize(self, cwd):
        stage = 'initialize'
        try:
            await self.race_cancel(self.rpc.request('initialize', dict(protocolVersion=1, clientCapabilities={})))
            stage = 'new-session'
            session = await self.race_cancel(self.rpc.request('session/new', dict(cwd=cwd, mcpServers=[])))
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
            outcome = None if cancelled or isinstance(error, AcpRunFailure) else await self.observe_outcome()
            failure = error if isinstance(error, AcpRunFailure) else AcpRunFailure(stage,
                'transport' if outcome is None else 'process-exit', error, outcome)
            if not cancelled:
                self.report(self.startup_report_error(error))
            try:
                await self.dispose_process()
            except Exception as cleanup_error:
                self.report(cleanup_error)
                outcome = self.process_outcome()
                cleanup = AcpRunFailure('teardown', 'unknown' if outcome is None else 'process-exit', cleanup_error, outcome)
                if cancelled:
                    raise AggregateError([cleanup], str(cleanup))
                raise AggregateError([failure, cleanup], str(failure) + '; ' + str(cleanup))
            if cancelled:
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise RuntimeError('subagent request was aborted before the ACP child started')
            raise failure
        finally:
            self.starting = False
        diagnostic = UNDEFINED

        async def attempt():
            nonlocal diagnostic
            try:
                response = await self.race_cancel(self.rpc.request('session/prompt',
                    dict(sessionId=self.remote_session_id, prompt=to_acp_prompt(self.request['prompt']))))
                reason = response.get('stopReason')
                stop_reason = acp_stop_reason(reason)
                if reason == 'max_turn_requests':
                    diagnostic = failure_diagnostic('prompt', 'remote-limit', stop_reason=reason)
                elif reason not in ('end_turn', 'max_tokens', 'refusal', 'cancelled'):
                    diagnostic = failure_diagnostic('prompt', 'unknown', stop_reason='unknown')
                permission = self.permission_diagnostic()
                if reason != 'end_turn' and permission is not None:
                    diagnostic = permission if diagnostic is UNDEFINED else diagnostic + '\n' + permission
                result = dict(output=self.output(), stopReason=stop_reason)
                if diagnostic is not UNDEFINED:
                    result['diagnostic'] = diagnostic
                return result
            except Exception as error:
                if not self.cancelled:
                    outcome = await self.observe_outcome()
                    diagnostic = failure_diagnostic('prompt' if outcome is None else 'process',
                        'transport' if outcome is None else 'process-exit', outcome)
                    permission = self.permission_diagnostic()
                    if permission is not None:
                        diagnostic += '\n' + permission
                raise self.process_failure or error

        self.result = settle_run_result(dict(attempt=attempt, collectOutput=self.output,
            collectDiagnostic=lambda: diagnostic, cancelled=lambda: self.cancelled, onError=self.on_error,
            signal=self.request['signal'], onAbort=self.abort_listener))
        return self

    def dispose(self):
        if self.public_disposal is None:
            self.public_disposal = start_coroutine(self.dispose_owned())
            self.public_disposal.add_done_callback(observe)
        return self.public_disposal


class CandidateAcpProvider:
    capabilities = NO_START_CAPABILITIES
    inheritsParentContext = False

    def __init__(self, ctx, config):
        self.ctx, self.config, self.name = ctx, config, config['providerName']

    def report(self, error, reason):
        self.ctx.logger.warn('subagent-acp "%s": child run failed (%s): %s', self.name, reason, error)

    async def start(self, request):
        if request['signal'].aborted:
            raise RuntimeError('subagent request was aborted before the ACP child started')
        try:
            cwd = assert_usable_cwd('subagent-acp', 'child cwd', request['cwd'])
        except Exception as error:
            self.ctx.logger.warn('subagent-acp "%s": child start failed: %s', self.name, error)
            raise AcpRunFailure('initialize', 'configuration', error)
        spec = SubprocessSpawnSpec([self.config['command']] + self.config['args'], cwd,
            SubprocessStdio('pipe', 'pipe', 'inherit'), self.config['disposeGraceMs'], env=self.config['env'])
        try:
            child = self.ctx.get('subprocess').spawn(spec)
        except Exception as error:
            try:
                self.report(error, 'error')
            except Exception:
                pass
            raise AcpRunFailure('process', 'process-start', error)
        return await CandidateAcpRun(child, request, self.config, self.report).initialize(cwd)


class CandidateSubagentAcp(Plugin):
    id = 'subagent-acp'
    inject = ['subagents', 'subprocess']
    Config = Schema.object(dict(providerName=Schema.string().default('acp'), command=Schema.string().required(),
        args=Schema.array(Schema.string()).default([]), permission=Schema.union(['allow', 'reject']).default('reject'),
        env=Schema.dict(Schema.string()).default({}), disposeEofGraceMs=Schema.number().default(6000), disposeGraceMs=Schema.number().default(3000)))

    def apply(self, ctx):
        config = dict(self.config)
        for name in ('disposeEofGraceMs', 'disposeGraceMs'):
            value = config[name]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or value > MAX_TIMER_DELAY_MS:
                raise RuntimeError('subagent-acp: %s must be a positive finite number no greater than %s' % (name, MAX_TIMER_DELAY_MS))
        ctx.get('subagents').registerProvider(CandidateAcpProvider(ctx, config))
