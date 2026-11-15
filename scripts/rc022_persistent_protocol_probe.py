"""Actual persistent tool/terminal registry under controlled PTY transcripts."""
import asyncio
import copy
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
    from dsh.core.abort import AbortController
    from dsh.terminal.service import TerminalSessionService
    from dsh.terminal.authorized import AuthorizedPersistentPwshPlugin
    base=workspace or WORKSPACE
    fixture=await setup(base/'native');ctx=fixture.ctx;rows=[]
    try:
        await ctx.plugin(TerminalSessionService)
        handle=await ctx.agents.create(dict(sessionId='protocol',agentOptions=dict(provider='script',model='model')));agent=handle.agent
        cases=json.loads((ROOT/'scripts/oracles/rc022_persistent_protocol_cases.json').read_text(encoding='utf-8'))
        for index,original in enumerate(cases):
            case=copy.deepcopy(original);sessions=[];controller=AbortController();attempts=[0]
            class Session:
                motd='';pid=123
                def __init__(self):self.text='';self.closed=False;self.value=dict(kind='running');self.steps=list(case['steps']);self.markers={}
                def status(self):return self.value
                def startSend(self,request):
                    step=self.steps.pop(0)
                    if step.get('error'):raise RuntimeError(step['error'])
                    if request['text']:
                        self.markers=dict(START=re.search(r'__DSH_PERSISTENT_PWSH_START_[^_]+__',request['text'])[0],END=re.search(r'__DSH_PERSISTENT_PWSH_END_[^:]+:',request['text'])[0],WRAPPER=request['text'])
                    text=step['text']
                    for key in ('WRAPPER','START','END'):text=text.replace('$'+key,self.markers[key])
                    self.text+=text
                    if step.get('exit'):self.value=step['exit']
                    result=dict(viewport='' if case.get('incremental') else text,waitReason=step.get('wait','stdin_read'),sessionStatus=self.value,truncated=False)
                    done=asyncio.get_running_loop().create_future()
                    if step.get('onAbort'):
                        request['signal'].add_listener('abort',lambda *_:done.set_result(result) if not done.done() else None)
                        if case.get('cancel'):asyncio.get_running_loop().call_soon(controller.abort,RuntimeError('caller cancelled'))
                    else:done.set_result(result)
                    if step.get('afterExit'):self.value=step['afterExit']
                    return NS(done=done,readOutput=lambda:dict(delta=text if case.get('incremental') else '',truncated=False),cancel=lambda:False)
                def read(self,request):
                    if case.get('emptyRead'):return dict(text='',totalLines=0,lineBegin=0,lineEnd=0,truncated=False)
                    lines=self.text.split('\n');offset=request.get('offset',0);end=len(lines)-offset;begin=max(0,end-case.get('pageLines',len(lines)))
                    return dict(text='\n'.join(lines[begin:end]),totalLines=len(lines),lineBegin=offset,lineEnd=offset+end-begin,truncated=case.get('historyTruncated',False))
                async def close(self,reason):self.closed=True
            async def spawn(spec):
                attempts[0]+=1
                if case.get('spawnFailure') and attempts[0]==1:raise RuntimeError('spawn failed')
                session=Session();sessions.append(session);return session
            ctx.terminals.registerBackend(NS(type='stub-'+str(index),spawn=spawn))
            plugin=await ctx.plugin(AuthorizedPersistentPwshPlugin,dict(backendType='stub-'+str(index),timeoutMs=case.get('timeout',1000),maxOutputChars=case.get('maximum',16000)))
            async def call():
                try:return dict(value=await ctx.tools.get('pwsh').execute(dict(command='fixture'),NS(agent=agent,signal=controller.signal)))
                except Exception as error:return dict(error=str(error))
            row=dict(name=case['name'],result=await call())
            if case.get('retry'):
                case['steps']=[dict(text='$START\nrecovered\n$END0\n')];row['retry']=await call()
            row['retainedBeforeUnload']=len(ctx.terminals.list(agent))
            await plugin.dispose();row.update(allocations=len(sessions),closed=all(session.closed for session in sessions),retained=len(ctx.terminals.list(agent)))
            rows.append(row)
        await handle.dispose();return rows
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_persistent_protocol.mts','Actual persistent tool/terminal registry with nonce-dependent controlled transcripts: completion/padding/torn status, prompt partials, retained/paged/incremental fallback, Unicode clipping, exit statuses/races, timeout/caller cancellation, spawn/send failure retry and unload. The PTY backend is controlled; no process launch in this probe.',
        [Path(__file__).resolve(),ROOT/'dsh/terminal/persistent_authorized.py',ROOT/'dsh/terminal/authorized.py',ROOT/'scripts/oracles/rc022_persistent_protocol_cases.json'],prepare=prepare)
