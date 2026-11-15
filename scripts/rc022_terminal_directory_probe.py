"""Observe actual terminal consumers, controlling only native launch and PTY output."""
import asyncio
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.terminal.authorized import AuthorizedLocalTerminalPlugin, AuthorizedPersistentPwshPlugin
    from dsh.terminal.service import TerminalSessionService
    base=workspace or WORKSPACE;directory=base/'native-work';directory.mkdir();(directory/'moved').mkdir()
    fixture=await setup(base/'native',directory=directory);ctx=fixture.ctx;rows=[];launches=[];sessions=[]
    async def spawn_terminal(spec):
        launches.append(spec.cwd)
        raise RuntimeError('measured-launch')
    ctx.set_service('subprocess',NS(spawn_terminal=spawn_terminal))
    ctx.set_service('sandboxPolicy',NS(resolve=lambda _:dict(mode='danger-full-access',workspaceRoot=str(directory))))
    try:
        await ctx.plugin(TerminalSessionService)
        local=await ctx.plugin(AuthorizedLocalTerminalPlugin,dict(shellDialect='pwsh'))
        handle=await ctx.agents.create(dict(sessionId='terminal',meta=dict(cwd=str(directory)),agentOptions=dict(provider='script',model='model')));agent=handle.agent
        for name,request in [('initial',dict(type='shell')),('changed',dict(type='shell')),('explicit',dict(type='shell',cwd=str(directory)))]:
            if name=='changed':await ctx.workingDirectory.set(agent,'moved',fixture.signal)
            try:await ctx.terminals.spawn(agent,request,fixture.signal)
            except RuntimeError as error:rows.append(dict(name=name,error=str(error),cwd=launches[-1]))
        await local.dispose()
        class Session:
            motd='';pid=123
            def __init__(self,cwd):self.cwd,self.closed,self.text=cwd,False,''
            def status(self):return dict(kind='exited' if self.closed else 'running')
            def startSend(self,request):
                start=re.search(r'__DSH_PERSISTENT_PWSH_START_[^_]+__',request['text'])[0];end=re.search(r'__DSH_PERSISTENT_PWSH_END_[^:]+:',request['text'])[0]
                self.text=start+'\n'+self.cwd+'\n'+end+'0\n'
                done=asyncio.get_running_loop().create_future();done.set_result(dict(viewport=self.text,waitReason='stdin_read',sessionStatus=self.status(),truncated=False))
                return NS(done=done,readOutput=lambda:dict(delta=self.text,truncated=False),cancel=lambda:False)
            def read(self,request):return dict(text=self.text,totalLines=3,lineBegin=0,lineEnd=3,truncated=False)
            async def close(self,reason):self.closed=True
        async def spawn(spec):
            session=Session(spec['cwd']);sessions.append(session);return session
        ctx.terminals.registerBackend(NS(type='stub',spawn=spawn))
        plugin=await ctx.plugin(AuthorizedPersistentPwshPlugin,dict(backendType='stub'))
        async def run():return await ctx.tools.get('pwsh').execute(dict(command='pwd'),NS(agent=agent,signal=fixture.signal))
        rows.append(dict(name='persistent-first',value=await run(),allocations=len(sessions)))
        await ctx.workingDirectory.set(agent,'..',fixture.signal)
        rows.append(dict(name='persistent-reused',value=await run(),allocations=len(sessions),current=ctx.workingDirectory.get(agent.session)))
        await plugin.dispose();rows.append(dict(name='persistent-unload',closed=all(session.closed for session in sessions),retained=len(ctx.terminals.list(agent))))
        plugin=await ctx.plugin(AuthorizedPersistentPwshPlugin,dict(backendType='stub'))
        rows.append(dict(name='persistent-recreated',value=await run(),allocations=len(sessions)))
        await handle.dispose();await ctx.fiber.dispose();rows.append(dict(name='owner-unload',closed=all(session.closed for session in sessions)))
        def normalize(value):
            if isinstance(value,str) and str(directory) in value:return value.replace(str(directory),'<work>').replace('\\','/')
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            if isinstance(value,list):return [normalize(item) for item in value]
            return value
        return normalize(rows)
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_terminal_directory.mts','Actual Session/WorkingDirectory and terminal registry: local backend launch cwd before/after directory change and explicit override; persistent pwsh creation, reuse across directory change, unload and recreation. Native process launch throws after capturing its spec; PTY backend output is a controlled nonce transcript. No browser terminal or complete persistent protocol parity claim.',
        [Path(__file__).resolve()]+[ROOT/path for path in ('dsh/terminal/local.py','dsh/terminal/persistent_pwsh.py','dsh/terminal/authorized.py')],prepare=prepare)
