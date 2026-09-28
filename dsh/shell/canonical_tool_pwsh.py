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
        ctx.get('systemPrompt').section(dict(name='tool:pwsh', order=105,
            text='Non-zero exits are reported as [exit code: N] markers; investigate failures before moving on.'))
        fields = dict(command={'type': 'string'}, description={'type': 'string'},
                      timeoutMs={'type': 'number'}, workdir={'type': 'string'})
        if background:
            fields['run_in_background'] = {'type': 'boolean'}
        if confined:
            fields.update(sandbox_permissions={'type': 'string', 'enum': ['workspace-write', 'danger-full-access']},
                          justification={'type': 'string'})

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
            description += ' Read-only PowerShell uses ConstrainedLanguage: prefer cmdlets and core types. A denied command may be retried once with the narrowest wider sandbox_permissions and justification; approval must succeed before execution. Rejected escalation is final for that command.'
        ctx.get('tools').register(dict(name='pwsh', description=description, parameters=parameters, execute=execute,
            output=dict(schema=OUTPUT, render=lambda args, value: [{'type': 'text', 'text': render_foreground(value, confined)}])))
