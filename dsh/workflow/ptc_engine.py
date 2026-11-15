"""Current Workflow engine contract with the explicit private-JS Win7 overlay.

The upstream default needs Node TypeScript PTC. This provider deliberately uses
jsRuntime for Workflow bodies and leaves the user-facing Python PTC untouched.
"""
import copy
import os
import re
import uuid
from types import SimpleNamespace

from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from .ptc_executor import QuickJsWorkflowExecutor
from .ptc_run import PtcWorkflowRun
from .workflow_service import WorkflowError, emit_workflow, safe_integer, validate_meta
from .text import js_trim


DEFAULTS = dict(provider='spawn', maxConcurrentAgents=0, maxTotalAgents=1000,
                maxItemsPerCall=4096, syncTimeoutMs=5000)


class PtcWorkflowEngine(Service):
    inject = ['subagents', 'jsRuntime', 'sandboxPolicy', 'workingDirectory']
    Config = Schema.object(dict(provider=Schema.string().default('spawn'), **{
        key: Schema.number().default(value) for key, value in DEFAULTS.items() if key != 'provider'}))

    def __init__(self, ctx, config=None):
        self.config = dict(DEFAULTS, **(config or {}))
        if set(self.config) != set(DEFAULTS):
            raise TypeError('workflow-ptc: unsupported config')
        for key in DEFAULTS:
            if key != 'provider' and not safe_integer(self.config[key], 0 if key == 'maxConcurrentAgents' else 1):
                raise TypeError('workflow config %s must be a %ssafe integer' % (key, 'non-negative ' if key == 'maxConcurrentAgents' else 'positive '))
        if not isinstance(self.config['provider'], str):
            raise TypeError('workflow provider must be a string')
        self.parser = ctx.get('jsRuntime')
        self.executor = QuickJsWorkflowExecutor(self.parser)
        super().__init__(ctx, 'workflowEngine')

    def start(self, request):
        meta = validate_meta(request.get('meta'))
        body = request.get('script')
        if not isinstance(body, str):
            raise WorkflowError('workflow script must be a string', 'SCRIPT_PARSE')
        if re.match(r'^\s*export\s+const\s+meta\b', body):
            raise WorkflowError('workflow meta rides the `meta` request field, not the script: remove the `export const meta = {...}` statement from the body', 'SCRIPT_PARSE')
        try:
            self.parser.parse(body, 'workflow:' + meta['name'])
        except Exception as error:
            if getattr(error, 'code', None) != 'SCRIPT_PARSE':
                raise
            raise WorkflowError('workflow script does not parse: ' + str(error), 'SCRIPT_PARSE') from error
        subagents = self.ctx.get('subagents')
        route = request.get('subagentProvider', self.config['provider'])
        if not isinstance(route, str) or not route or route != js_trim(route):
            raise WorkflowError('workflow subagentProvider must be a non-empty normalized string', 'INVALID_ARGUMENT')
        if subagents.getProvider(route) is None:
            raise WorkflowError('no subagent provider registered for "%s"' % route, 'AGENT_START')
        total = request.get('maxTotalAgents', self.config['maxTotalAgents'])
        if not safe_integer(total):
            raise WorkflowError('workflow maxTotalAgents must be a positive safe integer', 'INVALID_ARGUMENT')
        if total > self.config['maxTotalAgents']:
            raise WorkflowError('workflow maxTotalAgents %s exceeds the engine ceiling %s' % (total, self.config['maxTotalAgents']), 'INVALID_ARGUMENT')
        parent = request['parent']
        run_id = str(uuid.uuid4())
        info = dict(id=run_id, meta=meta)
        limits = {key: self.config[key] for key in ('maxConcurrentAgents', 'maxItemsPerCall', 'syncTimeoutMs')}
        limits['maxTotalAgents'] = total
        limits['maxConcurrentAgents'] = limits['maxConcurrentAgents'] or min(16, max(1, (os.cpu_count() or 1) - 2))
        initial = dict(meta=meta, body=body, limits=limits)
        if 'args' in request:
            initial['args'] = copy.deepcopy(request['args'])
        ctx = self.ctx
        def event(name):
            return lambda value: emit_workflow(ctx, name, info, value)
        observer = SimpleNamespace(phase=event('workflow/phase'), log=event('workflow/log'),
                                   agentStart=event('workflow/agent-start'), agentEnd=event('workflow/agent-end'))
        run = PtcWorkflowRun(ctx, subagents, self.executor, run_id, meta, parent, initial, route,
                             ctx.get('sandboxPolicy').resolve(dict(session=parent.session)), observer, request.get('signal'))
        run.info = info
        emit_workflow(ctx, 'workflow/start', info)
        def ended(done):
            result = done.result()
            emit_workflow(ctx, 'workflow/end', info, {key: result[key] for key in ('stopReason', 'agentsStarted', 'error') if key in result})
        run.result.add_done_callback(ended)
        return run
