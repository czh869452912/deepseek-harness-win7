"""Official PowerShell tool consumer; all execution goes through ctx.shell."""
import asyncio
import os

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.llm.error import HarnessError
from dsh.shell.pwsh_executor import positive
from dsh.shell.tool_pwsh import pwsh_description, stream_text
from dsh.subprocess.local import _signal_aborted


WIDER = {'read-only': ['workspace-write', 'danger-full-access'], 'workspace-write': ['danger-full-access']}
HINT = '[sandbox: escalation available — retry this exact command once with sandbox_permissions (the narrowest wider mode that suffices) + justification; the approval prompt asks the user]'


def object_schema(fields, required):
    return dict(type='object', additionalProperties=False, properties=fields, required=required)


STREAM = object_schema({'text': {'type': 'string'}, 'truncated': {'type': 'boolean'},
                        'spillPath': {'type': 'string'}}, ['text', 'truncated'])
SANDBOX = object_schema({'mode': {'type': 'string'}, 'denied': {'type': 'boolean'},
                        'enforcement': {'type': 'string'}, 'runnerFailed': {'type': 'boolean'}}, ['mode', 'denied'])
OUTPUT = {'oneOf': [
    object_schema({'kind': {'const': 'background', 'type': 'string'}, 'jobId': {'type': 'string'}}, ['kind', 'jobId']),
    object_schema({'kind': {'const': 'foreground', 'type': 'string'},
                   'exitCode': {'oneOf': [{'type': 'integer'}, {'type': 'null'}]},
                   'signal': {'oneOf': [{'type': 'string'}, {'type': 'null'}]},
                   'timedOut': {'type': 'boolean'}, 'aborted': {'type': 'boolean'},
                   'timeoutMs': {'type': 'number'}, 'stdout': STREAM, 'stderr': STREAM, 'sandbox': SANDBOX},
                  ['kind', 'exitCode', 'signal', 'timedOut', 'aborted', 'timeoutMs', 'stdout', 'stderr'])]}


def denial_markers(sandbox, escalate):
    if not sandbox or not sandbox.get('denied'):
        return []
    return ['[sandbox: file access denied under {} mode]'.format(sandbox['mode'])] + ([HINT] if escalate else [])


def render_foreground(value, escalate):
    if value['kind'] == 'background':
        return 'started background job ' + value['jobId']
    out, err = [stream_text(value[name]['text'], value[name]['truncated'], value[name].get('spillPath')) for name in ('stdout', 'stderr')]
    body = out + (('\n' if out and not out.endswith('\n') else '') + '[stderr]\n' + err if err else '')
    body = body or '(no output)'
    markers = denial_markers(value.get('sandbox'), escalate)
    if value['timedOut']:
        markers.append('[timed out after {}ms]'.format(value['timeoutMs']))
    if value['signal'] is not None:
        markers.append('[killed by signal: {}]'.format(value['signal']))
    elif value['exitCode'] != 0:
        markers.append('[exit code: {}]'.format(value['exitCode']))
    return body + (('' if body.endswith('\n') else '\n') + '\n'.join(markers) if markers else '')


def aborted():
    error = HarnessError('tool call aborted', 'TOOL_ABORTED')
    error.name = 'AbortError'
    return error


class CanonicalToolPwsh(Plugin):
    inject = ['tools', 'shell', 'systemPrompt', 'shellEnv']
    Config = Schema.object({'enableRunInBackground': Schema.boolean().default(True)})

    def apply(self, ctx):
        background = self.config.get('enableRunInBackground', True)
        confined = ctx.get('shell').sandboxMode is not None
        if confined and ctx.get('sandboxPolicy') is None:
            raise ValueError('tool-pwsh: confining executor requires sandboxPolicy')
        ctx.get('systemPrompt').section(dict(name='tool:pwsh', order=1010,
            text='Non-zero exits are reported as `[exit code: N]` markers; investigate failures before moving on. '
            'On Windows a killed process settles as `[exit code: 1]` without a signal marker; treat a bare exit 1 after an interruption as a termination, not a command failure.'))
        fields = dict(command={'type': 'string', 'description': 'The PowerShell command to execute.'},
            description={'type': 'string', 'description': 'Clear, concise description of what this command does in active voice, 5-10 words (shown in the UI). Examples: "ls" → "List files in current directory"; "git status" → "Show working tree status"; "Get-Process" → "List running processes".'},
            timeoutMs={'type': 'number', 'description': 'Timeout in milliseconds. The executor applies its configured default and cap, and kills the command on expiry.'},
            workdir={'type': 'string', 'description': 'Working directory for this command. Defaults to the session workspace; a relative path is resolved against it.'})
        if background:
            fields['run_in_background'] = {'type': 'boolean', 'description': 'Run in the background and return a job id immediately (collect with job_output, stop with job_kill). No timeout applies.'}
        if confined:
            fields.update(sandbox_permissions={'type': 'string', 'enum': ['workspace-write', 'danger-full-access'],
                'description': 'The wider sandbox mode this command needs. Only valid as a one-shot retry of a command the sandbox just denied; requires justification and user approval.'},
                justification={'type': 'string', 'description': 'Required with sandbox_permissions: one sentence for the user explaining why this exact command needs the wider access.'})

        async def execute(args, execution):
            for name in ('command', 'description'):
                if not isinstance(args.get(name), str) or not args[name].strip():
                    raise ValueError('invalid {}: expected a non-empty string'.format(name))
            if 'timeoutMs' in args:
                positive('timeoutMs', args['timeoutMs'])
            mode, justification = args.get('sandbox_permissions'), args.get('justification')
            if (mode is None) != (justification is None):
                raise ValueError('sandbox_permissions and justification must be supplied together')
            if justification is not None and (not isinstance(justification, str) or not justification.strip()):
                raise ValueError('invalid justification: expected a non-empty sentence')
            agent, signal = getattr(execution, 'agent', None), getattr(execution, 'signal', None)
            session = getattr(agent, 'session', None)
            policy = ctx.get('sandboxPolicy').resolve({'session': session}) if confined else None
            if mode is not None:
                if not confined:
                    raise ValueError('sandbox_permissions is not available without a sandboxing executor')
                if mode not in WIDER.get(policy['mode'], []):
                    raise ValueError('sandbox escalation is not strictly wider than this call\'s current mode')
                approval = ctx.get('approval')
                if approval is None or agent is None:
                    raise ValueError('sandbox escalation requires an approval service and a calling agent')
                outcome = await approval.request(dict(agent=agent, toolName='pwsh',
                    callId=getattr(execution, 'callId', None), signal=signal,
                    reason='escalate sandbox to {}: {}'.format(mode, justification)))
                if outcome != 'allowed-once':
                    raise ValueError('sandbox escalation {}: command did not run'.format(outcome))
                policy = dict(policy, mode=mode)
            if _signal_aborted(signal):
                raise aborted()
            cwd = getattr(getattr(session, 'header', None), 'cwd', None)
            workdir = args.get('workdir', cwd)
            if workdir is not None and cwd and not os.path.isabs(workdir):
                workdir = os.path.abspath(os.path.join(cwd, workdir))
            request = dict(command=args['command'], dshEnv=ctx.get('shellEnv').collect(execution))
            if workdir is not None:
                request['workdir'] = workdir
            if 'timeoutMs' in args:
                request['timeoutMs'] = args['timeoutMs']
            if policy is not None:
                request['sandboxPolicy'] = policy
            shell = ctx.get('shell')
            if args.get('run_in_background') is True:
                if not background:
                    raise ValueError('run_in_background is disabled for this deployment')
                jobs = ctx.get('jobs')
                if jobs is None:
                    raise ValueError('background jobs unavailable: load jobs and tool-jobs')

                def start():
                    process = shell.start(shell.resolve(request))

                    async def finish():
                        await process.done
                        failed = process.sandbox and process.sandbox.get('runnerFailed')
                        return dict(status='failed' if failed else process.status,
                                    exitCode=process.exitCode, signal=process.signal)

                    def read():
                        result = process.readOutput()
                        notices = []
                        if result['lossy']:
                            paths = [result[key] for key in ('stdoutSpillPath', 'stderrSpillPath') if key in result]
                            notices.append('[some output was dropped from memory; full output: {}]'.format(', '.join(paths) or '(unavailable)'))
                        if process.sandbox and process.sandbox.get('runnerFailed'):
                            notices.append('[sandbox: the sandbox runner itself failed under {} mode — the command did not run; this is a sandbox problem, not a command failure]'.format(process.sandbox['mode']))
                        else:
                            notices += denial_markers(process.sandbox, confined)
                        body = result['delta']
                        return body + (('\n' if body and not body.endswith('\n') else '') + '\n'.join(notices) if notices else '')

                    return dict(done=asyncio.create_task(finish()), cancel=lambda *_: process.kill(), readOutput=read)

                job_id = jobs.start(dict(kind='pwsh', label=args['command'], owner=agent, run=start))
                return dict(kind='background', jobId=job_id)
            result = await shell.run(shell.resolve(dict(request, signal=signal)))
            if result['aborted']:
                raise aborted()
            return dict(result, kind='foreground')

        parameters = dict(type='object', properties=fields, required=['command', 'description'])
        description = pwsh_description(background)
        if confined:
            description += ' Under the Windows sandbox, read-only pwsh runs in PowerShell ConstrainedLanguage mode, while workspace-write stays in FullLanguage unless host policy says otherwise. In read-only, prefer cmdlets and core types (`[string]`, `[datetime]`, `[regex]`, `[guid]`); .NET static calls (`[System.IO.*]::`, `[math]::`), `Add-Type`, COM objects, and reflection fail with "only core types" errors. `-f` formatting, property access, and core cmdlets work. In both confined modes, programs cannot open named pipes, so a command that captures another program\'s output through piped stdio (Node.js `child_process.spawn`/`exec` with the default `stdio: \'pipe\'`) fails with EPERM, while `stdio: \'inherit\'` and `stdio: \'ignore\'` spawns work and PowerShell\'s own pipelines are unaffected. That EPERM is the documented boundary: do not retry the command another way — escalate the exact command once or restructure it to avoid capturing output. Attempting a command the sandbox may deny is safe and expected: run it and read the marker rather than assuming the denial. When a command is denied and a wider mode would let it succeed, escalate immediately in the same turn — the one sanctioned exception to a denial: retry the exact same command once with `sandbox_permissions` (the narrowest wider mode that suffices) plus a one-sentence `justification`. Do not detour through chat to ask permission first — the approval prompt raised by that retry is how the user consents. If the session states approval prompts are disabled, there is no exception: a denial is final — do not set `sandbox_permissions`. Never escalate speculatively: ground the request in a real denial — normally the one this command just hit; escalating up front is fine only when this session already denied the same access. A rejected escalation is final for that command — stop and explain, never work around it — but it does not forbid attempting or escalating other commands later.'
        ctx.get('tools').register(dict(name='pwsh', description=description, parameters=parameters, execute=execute,
            output=dict(schema=OUTPUT, render=lambda args, value: [{'type': 'text', 'text': render_foreground(value, confined)}])))
