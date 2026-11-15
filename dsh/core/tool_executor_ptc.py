"""PTC executor: private program transport over admitted registry capabilities."""
import math

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.utils import symbols, _UNDEFINED, _js_own_enumerable_keys, js_to_string
from dsh.cordis.json_text import stringify_json
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.core.ptc_calls import PtcCalls
from dsh.core.ptc_dispatches import PtcDispatches, ToolCallLimitExceededError
from dsh.core.ptc_sdk import render_tools_sdk_py
from dsh.core.ptc_sdk_ts import render_tools_sdk
from dsh.core.tool_calls import execute_tool_batch
from dsh.core.tool_pipeline import ToolExecutionPipeline
from dsh.core.tools import (Tool, ToolNotFoundError, CodeRunFailedError,
    RUN_CODE_NAME, _json_snapshot, _schema_violations, _error_message)
from dsh.llm.error import HarnessError
from dsh.llm.message import create_user_message
from dsh.sandbox.escalation import validate_escalation_args, approve_escalation, ESCALATION_TARGETS

DEFAULTS = dict(maxSubCallsPerMinute=1024, maxParallelSubCalls=10)
Config = Schema.object({name: Schema.natural().min(1).default(value) for name, value in DEFAULTS.items()})
PTC_ONLY_INSTRUCTION = '`run_code` is the only tool you can call directly — a tool call naming any other tool fails. Reach every tool the SDK declares below from inside the program.'
_DESCRIPTION = ('Clear, concise description of what this program does in active voice, 5-10 words (shown in the UI). '
    'Examples: "Count TODO markers across packages"; "Read failing test and its fixture"; "Rename config key in every cordis.yml".')
_ESCALATION = (' A sandbox escalation approves this complete program for one execution only. Nested tools retain '
    'their own policies and approvals. Request wider access only after evidence of a denial. Earlier effects '
    'may already have completed: inspect them before explicitly retrying. Programs are never replayed automatically.')


class CodeResetFailedError(HarnessError):
    def __init__(self, message):
        super().__init__(message, 'CODE_RESET_FAILED')


def require_ptc_runtime(ctx):
    runtime = ctx.get('ptcRuntime')
    if runtime is None:
        raise RuntimeError('dsh-tools: mode "ptc" requires a PTC runtime — load a ctx.ptcRuntime implementation (e.g. @deepseek-ai/dsh-ptc-runtime-node) or load @deepseek-ai/dsh-tool-executor-native')
    if runtime.language not in ('typescript', 'python'):
        raise RuntimeError('dsh-tools: no SDK renderer registered for runtime language %s (known: "typescript", "python")' % stringify_json(runtime.language))
    return runtime


def _flavor(runtime):
    language = 'Python' if runtime.language == 'python' else 'TypeScript'
    function = runtime.language == 'typescript' and getattr(runtime, 'programFormat', 'function-body') == 'function-body'
    program = ('the BODY of an async function (erasable syntax only; top-level `await` and `return` work)'
        if function else 'the program to execute')
    output = 'Only what you print or return is program output — curate it.' if function else 'Curate the program output.'
    return dict(description=('Execute a %s program against the available tools. Takes two required arguments: '
        '`code`, %s, and `description`, a short summary of what the program does. Call tools as '
        '`await tools.name(args)` per the declarations in the system prompt. %s Image-bearing subtool results are attached after the run.'
        % (language, program, output)), codeDescription=('The program: the body of an async TypeScript function.'
        if function else 'The %s program to execute, following this tool\'s execution instructions.' % language))


def _controls(runtime=None):
    controls = {}
    timeout = getattr(runtime, 'timeout', None)
    if runtime is None or timeout is not None:
        description = ('Positive elapsed-time budget in milliseconds, capped by the deployment maximum.' if runtime is None else
            'Positive elapsed-time budget in milliseconds, including nested tool and approval waits. Default %s; capped at %s. Zero does not disable the deadline.'
            % (js_to_string(timeout['defaultMs']), js_to_string(timeout['maxMs'])))
        controls['timeoutMs'] = dict(type='number', description=description)
    if runtime is None or getattr(runtime, 'sandboxMode', None) is not None:
        controls.update(sandbox_permissions=dict(type='string', enum=list(ESCALATION_TARGETS),
            description='Wider sandbox mode for this complete program execution; requires justification and approval.'),
            justification=dict(type='string', description='Reason this complete program needs wider access, shown to the user for approval. Use the language of the user’s current request.'))
    return controls


def _parameters(runtime=None):
    properties = dict(code=dict(type='string', description=_flavor(runtime)['codeDescription'] if runtime is not None else ''),
                      description=dict(type='string', description=_DESCRIPTION))
    properties.update(_controls(runtime))
    return dict(type='object', properties=properties, required=['code','description'])


def render_json_value(value):
    """Bound indentation at ten characters and avoid recursive JSON rendering."""
    chunks, tasks = [], [('value', value, 0, False)]
    while tasks:
        task = tasks.pop()
        if task[0] == 'text':
            chunks.append(task[1])
            continue
        _, current, depth, compact = task
        if not isinstance(current, (dict, list)):
            chunks.append(stringify_json(current))
            continue
        compact = compact or (depth+1)*2 > 10
        is_array = isinstance(current, list)
        keys = list(range(len(current))) if is_array else _js_own_enumerable_keys(current)
        chunks.append('[' if is_array else '{')
        end = ']' if is_array else '}'
        if not keys:
            chunks.append(end)
            continue
        tasks.append(('text', end if compact else '\n' + '  '*depth + end))
        for index in range(len(keys)-1, -1, -1):
            key = keys[index]
            prefix = ('' if index==0 else ',') if compact else ('\n' if index==0 else ',\n') + '  '*(depth+1)
            if not is_array:
                prefix += stringify_json(key) + (':' if compact else ': ')
            tasks.append(('value', current[key], depth+1, compact))
            tasks.append(('text', prefix))
    return ''.join(chunks)


class _RunCodeTool(Tool):
    def __init__(self, owner):
        self.owner = owner
        output_schema = dict(type='object', additionalProperties=False, properties=dict(
            logs=dict(type='array', items=dict(type='string')), result={}, sandbox=dict(type='object', additionalProperties=False,
                properties=dict(mode=dict(type='string', enum=['read-only','workspace-write','danger-full-access']),
                    denied=dict(type='boolean'), enforcement=dict(type='string', enum=['full','partial'])), required=['mode','denied'])), required=['logs'])
        super().__init__(RUN_CODE_NAME, '', {}, self._run, execution_mode='exclusive', canonical=True,
            present_call=lambda args: dict(card='generic', title=args['description'], kind='execute', rawInput=args['code']),
            output=dict(schema=output_schema, render=self._render))

    @property
    def description(self):
        runtime = require_ptc_runtime(self.owner.ctx)
        instructions = getattr(runtime, 'executionInstructions', '')
        return (_flavor(runtime)['description'] + (' '+instructions if instructions else '')
            + " Each program starts in the Session's current directory. Running programs keep their initial directory."
            + (_ESCALATION if getattr(runtime, 'sandboxMode', None) is not None else ''))

    @description.setter
    def description(self, value):
        pass

    @property
    def parameters(self):
        return _parameters(require_ptc_runtime(self.owner.ctx))

    @parameters.setter
    def parameters(self, value):
        pass

    def validate_arguments(self, args):
        # defineTool validates the static union of controls, while the model
        # schema projects only controls currently supported by the provider.
        return _schema_violations(args, _parameters(), '')

    def _render(self, args, value):
        rendered = '' if 'result' not in value else value['result'] if isinstance(value['result'], str) else render_json_value(value['result'])
        parts = [text for text in ('\n'.join(value['logs']), rendered) if text]
        sandbox = value.get('sandbox', {})
        if sandbox.get('enforcement') == 'partial':
            parts.append('File sandbox enforcement is partial on this host.')
        if sandbox.get('denied'):
            runtime = self.owner.ctx.get('ptcRuntime')
            parts.append('The %s file sandbox denied an operation.' % sandbox['mode']
                + (_ESCALATION if getattr(runtime, 'sandboxMode', None) is not None else ''))
        return [dict(type='text', text='\n'.join(parts) if parts else '(run_code completed with no output)')]

    def _policy(self, execution):
        policy = self.owner.ctx.get('sandboxPolicy')
        if policy is None:
            raise RuntimeError('dsh-tools: confined PTC runtime requires sandboxPolicy')
        return policy.resolve(dict(session=execution.agent.session) if execution.agent is not None else {})

    async def _run(self, args, execution):
        if not args['description'].strip():
            raise ValueError('invalid description: expected a non-empty string')
        runtime = require_ptc_runtime(self.owner.ctx)
        async def run(signal):
            permissions, justification = args.get('sandbox_permissions', _UNDEFINED), args.get('justification', _UNDEFINED)
            validate_escalation_args(permissions, justification)
            if 'timeoutMs' in args and getattr(runtime, 'timeout', None) is None:
                raise ValueError('timeoutMs is not available for this PTC runtime')
            if 'timeoutMs' in args and (type(args['timeoutMs']) not in (int, float) or not math.isfinite(args['timeoutMs']) or args['timeoutMs'] <= 0):
                raise ValueError('invalid timeoutMs: expected a positive finite number')
            standing = self._policy(execution) if getattr(runtime, 'sandboxMode', None) is not None else None
            policy = standing
            if permissions is not _UNDEFINED and justification is not _UNDEFINED:
                if standing is None:
                    raise ValueError('sandbox_permissions is not available for this PTC runtime')
                approved = await approve_escalation(dict(requestedMode=permissions, justification=justification,
                    effectiveMode=standing['mode'], subject='program'), dict(approver=self.owner.ctx.get('approval'),
                    agent=execution.agent, callId=execution.call_id, toolName=RUN_CODE_NAME, signal=signal))
                policy = dict(standing, mode=approved)
            cwd = None
            if execution.agent is not None:
                directories = self.owner.ctx.get('workingDirectory')
                if directories is None:
                    raise RuntimeError('dsh-tools: run_code with an Agent requires workingDirectory')
                cwd = await await_callback_result(directories.ensure(execution.agent, signal))
            signal.throwIfAborted()
            controller = AbortController()
            remove = subscribe_abort(signal, controller.abort)
            queue = PtcDispatches(self.owner.ctx, self.owner.pipeline, execution, controller,
                self.owner.config['maxParallelSubCalls'], math.inf, self.owner.config['maxSubCallsPerMinute'])
            functions = {schema['name']: queue.binding(schema) for schema in self.owner.registry.schemas(execution.agent, execution.toolSet)}
            try:
                try:
                    if execution.agent is not None:
                        self.owner._own_runtime(runtime, execution.agent)
                    request = dict(program=args['code'], bindings=[dict({'global':'tools'}, functions=functions,
                        errorClass=dict(name='ToolCallError', memberNameProperty='toolName'))], signal=controller.signal)
                    if execution.agent is not None and (None if policy is None else policy['mode']) == (None if standing is None else standing['mode']):
                        request['stateOwner'] = execution.agent
                    if cwd is not None:
                        request['cwd'] = cwd
                    if policy is not None:
                        request['sandboxPolicy'] = policy
                    if 'timeoutMs' in args:
                        request['timeoutMs'] = args['timeoutMs']
                    spec = runtime.resolve(request)
                    queue.max_calls = math.inf if spec['timeoutMs'] is None else math.floor(spec['timeoutMs']/60000*self.owner.config['maxSubCallsPerMinute'])
                    result = await await_callback_result(runtime.run(spec))
                finally:
                    controller.abort('run_code settled')
                    await queue.drain()
                if result.get('error') is not None:
                    error = result['error']
                    limit = controller.signal.reason if isinstance(controller.signal.reason, ToolCallLimitExceededError) else None
                    if error['kind'] == 'abort' and execution.signal.aborted and limit is None:
                        aborted = HarnessError('tool call aborted: '+error['message'] if getattr(runtime, 'retainsState', False) else 'tool call aborted', 'ABORTED')
                        aborted.name = 'AbortError'
                        raise aborted
                    failure = error['message'] if limit is None or limit.message == error['message'] else limit.message+'\n'+error['message']
                    logs = '\nCaptured output:\n'+'\n'.join(result['logs']) if result['logs'] else ''
                    sandbox = result.get('sandbox')
                    sandbox_text = ('' if sandbox is None else '\nFile sandbox: '+sandbox['mode']
                        + ('; enforcement: '+sandbox['enforcement'] if 'enforcement' in sandbox else '')
                        + ('; operation denied' if sandbox['denied'] else '') + '.')
                    raise CodeRunFailedError('code run failed (%s): %s%s%s%s' % (error['kind'], failure, logs, sandbox_text,
                        _ESCALATION if sandbox is not None and sandbox['denied'] and getattr(runtime, 'sandboxMode', None) is not None else ''))
                output = dict(logs=result['logs'])
                if 'value' in result:
                    output['result'] = result['value']
                if 'sandbox' in result:
                    output['sandbox'] = result['sandbox']
                return output
            finally:
                remove()
        if execution.agent is None or (getattr(runtime, 'sandboxMode', None) is None and not getattr(runtime, 'retainsState', False)):
            return await run(execution.signal)
        return await self.owner.calls.run(execution.agent.session.id, execution.signal,
            lambda: None if getattr(runtime, 'sandboxMode', None) is None else self._policy(execution)['mode'], run)


class PtcExecutor:
    def __init__(self, ctx, config=None, max_parallel=None):
        self.ctx, self.config = ctx, dict(DEFAULTS, **(config or {}))
        for key in DEFAULTS:
            value = self.config[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 1 or value != int(value):
                raise ValueError(key + ' must be a positive natural number')
            self.config[key] = int(value)
        self.max_parallel = max_parallel or (lambda: 10)
        self.registry, self.calls = ctx.get('tools'), PtcCalls(ctx)
        self.transport = None
        self.state_owners = set()
        self.pipeline = ToolExecutionPipeline(ctx, dict(get=lambda name, scope, tool_set: self.require_transport()
            if name == RUN_CODE_NAME else self.registry.executable(name, scope, tool_set),
            reject=lambda name, nested: ToolNotFoundError(name,
                'only `run_code` is callable directly — call `%s` from inside a `run_code` program instead' % name)
                if not nested and name != RUN_CODE_NAME else None))
        prompt = ctx.get('systemPrompt')
        self.sections = [dict(name='tools:ptc-only', order=prompt.getSectionOrder('PTC_ONLY'), text=PTC_ONLY_INSTRUCTION, interpolate=False),
            dict(name='tools:sdk', order=prompt.getSectionOrder('TOOLS_SDK'), text=self.render_sdk, interpolate=False)]

    def require_transport(self):
        if self.transport is None:
            self.transport = _RunCodeTool(self)
        return self.transport

    def describe(self, tools):
        return dict(schemas=[self.require_transport().schema()], knownNames=[RUN_CODE_NAME])

    def render_sdk(self, tools):
        runtime = require_ptc_runtime(self.ctx)
        schemas = [dict(tool.schema(), output=tool.output['schema']) for tool in tools]
        return render_tools_sdk_py(schemas) if runtime.language == 'python' else render_tools_sdk(schemas, getattr(runtime, 'programFormat', 'function-body'))

    async def execute(self, input):
        return await execute_tool_batch(self.ctx, input, self.pipeline, self.max_parallel)

    def _own_runtime(self, runtime, agent):
        provider = runtime
        while True:
            original = getattr(provider, symbols.original, None)
            if original is None or original is provider:
                break
            provider = original
        key = (id(agent), id(provider))
        if key in self.state_owners:
            return
        async def cleanup():
            try:
                await await_callback_result(runtime.release(agent))
            finally:
                self.state_owners.discard(key)
        agent.ctx.effect(lambda: cleanup, label='PTC retained environment')
        self.state_owners.add(key)

    async def reset(self, agent):
        runtime = require_ptc_runtime(self.ctx)
        if not getattr(runtime, 'retainsState', False):
            raise CodeResetFailedError('The PTC runtime does not retain an environment')
        try:
            await self.calls.reset(agent.session.id, lambda: runtime.release(agent), lambda: agent.inject(create_user_message(dict(
                content=[dict(type='text', text='Program environment reset; retained variables cleared. Completed tool effects remain.')], source=dict(kind='ptc-mode')))))
        except Exception as error:
            raise CodeResetFailedError('Program environment reset failed: %s. State may not be cleared; retry the host reset before running more code.' % _error_message(error))


class PtcToolExecutorPlugin(Plugin):
    id = 'ptc-tool-executor'
    inject = ['tools', 'systemPrompt', 'ptcRuntime']
    Config = Config

    def apply(self, ctx, config=None):
        ctx.tools.setExecutor(PtcExecutor(ctx, config or self.config))
