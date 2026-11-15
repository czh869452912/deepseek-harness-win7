"""Current PowerShell tool: job admission, foreground collection and promotion."""
import copy
import json
import math
import ntpath
from pathlib import Path
import re

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.fiber import FiberState
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.text import trim_js
from dsh.cordis.utils import _UNDEFINED,js_to_string
from dsh.core.tools import TOOL_ABORTED,ToolArgsError,ToolContextUnavailableError
from dsh.jobs.error import JobError
from dsh.jobs.pump import field
from dsh.llm.error import HarnessError
from dsh.sandbox.escalation_current import ESCALATION_TARGETS,SandboxEscalationError,validate_escalation_args,approve_escalation
from dsh.subprocess.error import subprocess_spawn_failure
from .jobs_current import process_job,process_outcome,process_sources,ring_delta
from .render_current import render_result,render_promoted,render_job_read
from .render import parse_exit_status

DEFINITIONS=json.loads((Path(__file__).parent/'pwsh_current.json').read_text(encoding='utf-8'))['definitions']


def tool_aborted():
    error=HarnessError('tool call aborted',TOOL_ABORTED);error.name='AbortError';return error


def canonical_result(result,cwd):
    value={key:result[key] for key in ('exitCode','signal','timedOut','aborted','timeoutMs')};value.update(cwd=cwd,kind='foreground')
    for name in ('stdout','stderr'):value[name]={key:result[name][key] for key in ('text','truncated','spillPath') if key in result[name]}
    if 'sandbox' in result:value['sandbox']={key:result['sandbox'][key] for key in ('mode','denied','enforcement','runnerFailed') if key in result['sandbox']}
    return value


class CurrentToolPwsh(Plugin):
    name='tool-pwsh'
    inject=['tools','shell','systemPrompt','shellEnv','workingDirectory']
    Config=Schema.object(dict(enableRunInBackground=Schema.boolean().default(True),promoteOnTimeout=Schema.boolean().default(True)))

    def apply(self,ctx):
        enabled=self.config.get('enableRunInBackground',True);promote_timeout=self.config.get('promoteOnTimeout',True) and enabled
        confined=ctx.shell.sandboxMode is not None;escalation_modes=ESCALATION_TARGETS if confined else []
        sandbox_policy=ctx.get('sandboxPolicy') if confined else None
        if confined and sandbox_policy is None:raise RuntimeError('tool-pwsh: the mounted bash executor confines but ctx.sandboxPolicy is missing')
        ctx.systemPrompt.section(dict(name='tool:pwsh',order=ctx.systemPrompt.getSectionOrder('TOOL_PWSH'),text='Non-zero exits are reported as `[exit code: N]` markers; investigate failures before moving on. On Windows a killed process settles as `[exit code: 1]` without a signal marker; treat a bare exit 1 after an interruption as a termination, not a command failure.'))
        def launch_failure(error,signal):return error if signal.aborted and error is signal.reason else subprocess_spawn_failure(error,'pwsh')

        def definition(jobs):
            promote=jobs is not None and promote_timeout
            variant='foreground' if jobs is None else 'promote' if promote else 'background'
            descriptor=copy.deepcopy(DEFINITIONS[('confined-' if confined else 'local-')+variant])
            def start_job(args,execution,spec):
                state=dict(process=None,stopped=None,hooks=None)
                async def start(signal):
                    state['process']=await await_callback_result(ctx.shell.execute(dict(spec,signal=signal)));return state['process']
                def run(_handle):
                    hooks=process_job(start,lambda process:process_outcome(process,escalation_modes));state['hooks']=hooks
                    def cancel(reason):state['stopped']=reason;hooks.cancel(reason)
                    return dict(done=hooks.done,cancel=cancel)
                tool_call=dict(callId=execution.callId)
                if execution.rootCallId is not None:tool_call['rootCallId']=execution.rootCallId
                identity=jobs.start(dict(kind='pwsh',label=args['command'],toolCall=tool_call,output=process_sources(lambda:state['process']),run=run,**({} if execution.agent is None else dict(owner=execution.agent.id))))
                state['id']=identity;return state
            async def wait_on_job(attached,execution,spec):
                identity=attached['id'];owner=execution.agent.id if execution.agent is not None else None;timeout=spec['timeoutMs']
                async def stop(reason):
                    jobs.kill(identity,owner,reason);settled=await jobs.wait(identity,timeout,owner)
                    if settled['status'] not in ('running','stopping'):jobs.remove(identity,owner)
                    return settled
                try:view=await jobs.wait(identity,timeout,owner,execution.signal)
                except Exception:
                    await stop('tool call aborted');raise tool_aborted()
                if view['status'] in ('running','stopping') and attached['process'] is None:
                    await stop('timed out during preparation')
                    return dict(kind='foreground',cwd=spec['workdir'],exitCode=None,signal=None,timedOut=True,aborted=False,timeoutMs=timeout,stdout=dict(text='',truncated=False),stderr=dict(text='',truncated=False),**({} if 'sandboxPolicy' not in spec else dict(sandbox=dict(mode=spec['sandboxPolicy']['mode'],denied=False))))
                if view['status'] in ('running','stopping'):
                    read=jobs.read(identity,owner)
                    return dict(kind='promoted',cwd=spec['workdir'],jobId=identity,timeoutMs=timeout,output=render_job_read(ring_delta(read['chunks']),read['lossy'],read['job']['output'].get('spillPaths',[]),field(attached['process'],'sandbox'),escalation_modes))
                jobs.remove(identity,owner);process=attached['process']
                if process is None:
                    failure=attached['hooks'].failure()
                    raise RuntimeError(view.get('detail','')) if failure is None else launch_failure(failure['error'],execution.signal)
                try:result=await field(process,'result')()
                except Exception as error:raise launch_failure(error,execution.signal)
                value=canonical_result(result,spec['workdir'])
                if attached['stopped'] is not None:value['stopped']=attached['stopped']
                return value
            async def execute(args,execution):
                for key in ('command','description'):
                    if not trim_js(args[key]):raise ToolArgsError('pwsh',['invalid '+key+': expected a non-empty string'])
                if 'timeoutMs' in args and (type(args['timeoutMs']) not in (int,float) or not math.isfinite(args['timeoutMs']) or args['timeoutMs']<=0):raise ToolArgsError('pwsh',['invalid timeoutMs: expected a positive number, got '+stringify_json(args['timeoutMs'])])
                mode=args.get('sandbox_permissions',_UNDEFINED);justification=args.get('justification',_UNDEFINED);validate_escalation_args(mode,justification)
                agent=execution.agent;policy=sandbox_policy.resolve(dict(session=agent.session) if agent is not None else {}) if sandbox_policy is not None else None
                if mode is not _UNDEFINED and justification is not _UNDEFINED:
                    if not escalation_modes:raise SandboxEscalationError('sandbox_permissions is not available in this composition (no sandboxing executor to escalate)','SANDBOX_ESCALATION_UNAVAILABLE')
                    approved=await approve_escalation(dict(requestedMode=mode,justification=justification,effectiveMode=policy['mode'],subject='command'),dict(approver=ctx.get('approval'),agent=agent,callId=execution.callId,toolName='pwsh',signal=execution.signal))
                    policy=dict(policy,mode=approved)
                cwd=None if agent is None else await await_callback_result(ctx.workingDirectory.ensure(agent,execution.signal));workdir=args.get('workdir',cwd)
                if workdir is not None and cwd is not None and not ntpath.isabs(workdir):workdir=ntpath.abspath(ntpath.join(cwd,workdir))
                request=dict(command=args['command'],dshEnv=ctx.shellEnv.collect(execution))
                if workdir is not None:request['workdir']=workdir
                if 'timeoutMs' in args:request['timeoutMs']=args['timeoutMs']
                if policy is not None:request['sandboxPolicy']=policy
                if args.get('run_in_background') is True:
                    if not enabled:raise JobError('run_in_background is disabled for this deployment (enableRunInBackground: false)','JOB_BACKGROUND_DISABLED')
                    if jobs is None:raise ToolContextUnavailableError('background jobs unavailable: load @deepseek-ai/dsh-jobs and @deepseek-ai/dsh-tool-jobs')
                    if execution.signal.aborted:raise tool_aborted()
                    spec=ctx.shell.resolve(dict(request,onExpiry='none'));return dict(kind='background',jobId=start_job(args,execution,spec)['id'],cwd=spec['workdir'])
                if jobs is not None and promote:
                    spec=ctx.shell.resolve(dict(request,onExpiry='none'));attached=None
                    try:attached=start_job(args,execution,spec)
                    except Exception as error:ctx.logger.warn('pwsh: job registration refused, running in the foreground with the timeout kill instead: '+js_to_string(error))
                    if attached is not None:return await wait_on_job(attached,execution,spec)
                spec=ctx.shell.resolve(dict(request,signal=execution.signal))
                try:result=await field(await await_callback_result(ctx.shell.execute(spec)),'result')()
                except Exception as error:raise launch_failure(error,execution.signal)
                if result['aborted']:raise tool_aborted()
                return canonical_result(result,spec['workdir'])
            def render(args,value):return [dict(type='text',text='started background job '+value['jobId'] if value['kind']=='background' else render_promoted(value) if value['kind']=='promoted' else render_result(value,escalation_modes))]
            def present_call(args):
                if args.get('run_in_background') is True:return dict(card='generic',title=args['command'],kind='execute',rawInput=args['command'],content=[dict(type='text',text=args['description'])])
                return dict(card='terminal',title=args['command'],description=args['description'],**({} if 'workdir' not in args else dict(cwd=args['workdir'])))
            def present_result(args,result):
                if len(result.content)!=1 or result.content[0].get('type')!='text':return None
                raw=result.content[0]['text']
                if args.get('run_in_background') is True or isinstance(result.value,dict) and result.value.get('kind')=='promoted' or result.is_error:return dict(card='generic',content=[dict(type='text',text='```console\n'+re.sub(r'\n+$','',raw)+'\n```')])
                exit=parse_exit_status(raw);body=exit.pop('body')
                return dict(card='terminal',output=body,**{('exitCode' if key=='exit_code' else key):value for key,value in exit.items()})
            descriptor.update(execute=execute,output=dict(schema=descriptor.pop('outputSchema'),render=render,presentationMeta=lambda args,value:dict(cwd=value['cwd'])),presentCall=present_call,presentResult=present_result)
            return descriptor
        if not enabled:ctx.tools.register(definition(None));return
        foreground=[ctx.tools.register(definition(None)) if ctx.get('jobs') is None else None]
        def available(job_ctx):
            if foreground[0] is not None:foreground[0]();foreground[0]=None
            unregister=ctx.tools.register(definition(job_ctx.jobs))
            def cleanup():
                unregister()
                if ctx.fiber.state==FiberState.ACTIVE:foreground[0]=ctx.tools.register(definition(None))
            job_ctx.effect(lambda:cleanup)
        ctx.inject(['jobs'],available)
