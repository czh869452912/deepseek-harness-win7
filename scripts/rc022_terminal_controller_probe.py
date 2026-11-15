"""Session terminal allocation, rollback and lifecycle paired with Source."""
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_browser_terminal_probe import Channel


async def fixture(config=None):
    from dsh.cordis import Context
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.terminal.screen_runtime import TerminalScreenRuntime
    from dsh.api.terminal_controller_authorized import AuthorizedTerminalController
    ctx=Context();calls=[];handles=[]
    class Handle:
        pid=123
        def __init__(self):
            self.output=Channel();self.done=asyncio.get_running_loop().create_future();self.terminated=0;self.failures=0
        async def write(self,data):calls.append(['write',data])
        async def resize(self,cols,rows):calls.append(['resize',cols,rows])
        async def inspectActivity(self):return dict(state='unknown',revision=0)
        async def inspectForeground(self):return None
        async def signalForeground(self,signal):return 123
        async def terminate(self):
            self.terminated+=1
            if self.failures:self.failures-=1;raise RuntimeError('cleanup failure')
            if not self.done.done():self.done.set_result(dict(exitCode=0,signal=None))
            await self.output.aclose()
    class Provider:
        gate=None;abort=None;platform='posix';default='/bin/bash'
        async def terminalEnvironment(self,signal):signal.throwIfAborted();return dict(platform=self.platform,defaultShell=self.default)
        async def resolveExecutable(self,path,env,signal):signal.throwIfAborted();return path
        async def spawnTerminal(self,spec):
            calls.append(['spawn',{key:value for key,value in spec.items() if key!='signal'}])
            handle=Handle();handles.append(handle)
            if self.gate is not None:await self.gate.wait()
            if self.abort is not None:self.abort.abort(RuntimeError('allocation cancelled'))
            return handle
        def spawn(self,spec):
            calls.append(['ordinary',spec]);done=asyncio.get_running_loop().create_future();done.set_result(dict(exitCode=0,signal=None))
            return SimpleNamespace(done=done)
    provider=Provider()
    directory=SimpleNamespace(get=lambda session:session.header.get('cwd','/workspace'))
    async def ensure(agent,signal):signal.throwIfAborted();return directory.get(agent.session)
    directory.ensure=ensure
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime)
        ctx.set_service('subprocess',provider);ctx.set_service('sandboxPolicy',SimpleNamespace(defaultMode='danger-full-access'));ctx.set_service('workingDirectory',directory)
        controller=AuthorizedTerminalController(ctx,dict(maxTerminals=2,maxAgentTerminals=1,shellCandidates=['bash','sh'],unattendedTimeoutMs=0,**(config or {})))
        agent=SimpleNamespace(id='session',ctx=ctx,session=SimpleNamespace(id='session',header={}))
        return ctx,controller,agent,provider,handles,calls
    except BaseException:await ctx.fiber.dispose();raise


async def observe():
    from dsh.core.abort import AbortController
    rows=[]
    def signal():return AbortController().signal
    async def error(operation):
        try:
            result=operation()
            if hasattr(result,'__await__'):result=await result
            return dict(value=result)
        except Exception as failure:return dict(error=str(failure),code=getattr(failure,'code',None),name=getattr(failure,'name','Error'))
    def record(name,controller,calls,handles,extra=None):
        rows.append(copy.deepcopy(dict(name=name,roster=controller.list('session'),calls=calls,terminations=[h.terminated for h in handles],extra=extra)))
    request=dict(id='one',cols=20,rows=4)
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        rows.append(dict(name='environment',value=controller.environment(agent,signal())))
        first=await controller.create(agent,request,signal());agent.session.header['cwd']='/changed';provider.default='/bin/sh'
        same=await controller.create(agent,request,signal())
        record('idempotent',controller,calls,handles,dict(same=same is first))
        await controller.create(agent,dict(request,id='two'),signal());record('directory',controller,calls,handles)
        rows.append(dict(name='capacity',result=await error(lambda:controller.create(agent,dict(request,id='three'),signal()))))
        await controller.close(agent,'one');rows.append(dict(name='closed-id',result=await error(lambda:controller.create(agent,request,signal()))))
        await controller.close(agent,'one');await controller.close(agent,'two');record('removed',controller,calls,handles)
        for bad in ('','bad.id','中','x'*129):
            rows.append(dict(name='bad-id',result=await error(lambda:controller.create(agent,dict(request,id=bad),signal()))))
        rows.append(dict(name='bad-size',result=await error(lambda:controller.create(agent,dict(request,id='new',cols=True),signal()))))
    finally:await ctx.fiber.dispose()
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        provider.gate=asyncio.Event()
        first=asyncio.ensure_future(controller.create(agent,request,signal()));await asyncio.sleep(0);await asyncio.sleep(0)
        second=asyncio.ensure_future(controller.create(agent,request,signal()));await asyncio.sleep(0)
        closing=asyncio.ensure_future(controller.close(agent,'one'));await asyncio.sleep(0);provider.gate.set()
        result=await asyncio.gather(first,second,closing,return_exceptions=True)
        record('close-during-allocation',controller,calls,handles,[str(value) if isinstance(value,Exception) else None for value in result])
    finally:await ctx.fiber.dispose()
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        abort=AbortController();provider.abort=abort
        result=await error(lambda:controller.create(agent,request,abort.signal));record('cancelled-allocation',controller,calls,handles,result)
        rows.append(dict(name='cancelled-id',result=await error(lambda:controller.create(agent,request,signal()))))
    finally:await ctx.fiber.dispose()
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        await controller.create(agent,request,signal());handles[0].failures=1
        rows.append(dict(name='cleanup-failure',result=await error(lambda:controller.close(agent,'one'))))
        record('retained-for-retry',controller,calls,handles);await controller.close(agent,'one');record('retry',controller,calls,handles)
    finally:await ctx.fiber.dispose()
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        # Launch metadata is directly observable before UUID allocation; pass a
        # fixed identity to compare sandbox/history semantics without masking IDs.
        async def confine(argv,policy,signal):calls.append(['confine',argv,policy]);return dict(argv=['confined']+argv)
        ctx.set_service('sandbox',SimpleNamespace(confine=confine))
        request_agent=dict(title='agent',cols=20,rows=4,preferredShells=['SH'],policy=dict(mode='workspace-write',workspaceRoot='/workspace'),env=dict(CUSTOM='yes',DSH_SESSION_ID='wrong',HISTFILE='wrong'))
        launch=await controller.agentLaunch(agent,'fixed-agent',request_agent,signal())
        rows.append(copy.deepcopy(dict(name='agent-launch',launch={key:value for key,value in launch.items() if key!='release'},calls=calls)))
        await launch['release']();record('history-cleanup',controller,calls,handles)
        handle=await controller.openForAgent(agent,dict(request_agent,policy=dict(mode='danger-full-access')),signal())
        rows.append(dict(name='agent-handle',origin=handle.info['origin'],control=handle.info['control'],title=handle.info['title'],pid=handle.pid))
        rows.append(dict(name='agent-capacity',result=await error(lambda:controller.openForAgent(agent,request_agent,signal()))))
        await handle.close()
    finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_terminal_controller.mts','Actual Source and native TerminalController with canonical controlled execution providers. Compares environment, idempotency, current directory capture, capacity, input validation, concurrent create/close exclusion, cancelled allocation rollback, cleanup failure retention/retry, sandbox argv and history cleanup. Native uses real unchanged xterm worker; Source uses its original xterm. No real PTY or frontend acceptance.',[Path(__file__).resolve(),ROOT/'dsh/api/terminal_controller_authorized.py'])
