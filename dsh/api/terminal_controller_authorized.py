"""Session-owned canonical terminal Remote service and Agent allocations."""
import asyncio
import inspect
import re
import uuid
from types import SimpleNamespace

from dsh.api.terminal_authorized import BrowserTerminal, AgentTerminalHandle
from dsh.api.terminal_retention_authorized import TerminalRetention, CleanupPromise
from dsh.api.terminal_shells_authorized import discover_shells, resolve_shell, find_shell
from dsh.api.terminal_screen_authorized import JS_WHITESPACE
from dsh.cordis.errors import AggregateError
from dsh.cordis.schema import Schema
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.core.session.current import safe
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService


def title(value):
    trimmed=value.strip(JS_WHITESPACE)
    if not trimmed or len(value.encode('utf-16-le','surrogatepass'))//2 > 120:
        raise ValueError('Terminal title must contain 1–120 characters')
    return trimmed


def consume(task):
    if not task.cancelled():task.exception()


async def settle(operations, message):
    results=await asyncio.gather(*operations,return_exceptions=True)
    errors=[result for result in results if isinstance(result,BaseException)]
    if errors:raise AggregateError(errors,message)


class AuthorizedTerminalController(TypertRemoteService):
    inject=['subprocess','sandboxPolicy','workingDirectory','typert','terminalScreens']
    Config=Schema.object(dict(
        shell=Schema.union([Schema.object(dict(path=Schema.string().required(),name=Schema.string().required(),args=Schema.array(Schema.string()).default([]))),Schema.const_()]),
        shellCandidates=Schema.array(Schema.string().min(1)).default(['zsh','bash','fish','pwsh','powershell','cmd']),
        maxTerminals=Schema.natural().min(1).default(8),maxAgentTerminals=Schema.natural().min(1).default(4),
        maxCols=Schema.natural().min(2).default(500),maxRows=Schema.natural().min(1).default(200),
        scrollback=Schema.natural().default(1000),maxBufferedBytes=Schema.natural().min(1024).default(2097152),
        maxInputBytes=Schema.natural().min(1).default(65536),disposeGraceMs=Schema.natural().min(1).default(1000),
        unattendedTimeoutMs=Schema.natural().max(9007199254740991).default(7200000),
        activityPollIntervalMs=Schema.natural().min(1).max(9007199254740991).default(30000),
        cleanupRetryMs=Schema.natural().min(1).max(9007199254740991).default(60000)))

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'terminalController',dict(namespace='terminal'))
        self.config=self.Config(config or {});self.owners={};self.rosters={};self.lifetime=AbortController()
        ctx.effect(lambda:self.dispose,'terminal-controller.processes')

    async def dispose(self):
        self.lifetime.abort(RuntimeError('Terminal controller disposed'))
        await settle([self.disposeOwner(identity,owner) for identity,owner in list(self.owners.items())],'Browser terminal cleanup failed')

    @Remote
    def environment(self,agent,signal):
        signal.throwIfAborted();_,_,directory=self.execution(agent)
        return dict(cwd=directory.get(agent.session),**{key:self.config[key] for key in ('maxInputBytes','maxBufferedBytes','maxCols','maxRows','scrollback')})

    @Remote
    async def shells(self,agent,signal):
        signal.throwIfAborted()
        return await discover_shells(self.execution(agent)[0],self.config.get('shell'),self.config['shellCandidates'],signal)

    @Remote
    def list(self,sessionId):
        owner=self.owners.get(sessionId)
        return [] if owner is None else [value.info for value in list(owner.terminals.values())+list(owner.allocations.values())]

    @Remote
    async def create(self,agent,request,signal):
        self.lifetime.signal.throwIfAborted()
        identity=request['id']
        if re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',identity) is None:raise ValueError('Invalid terminal identity')
        self.dimensions(request['cols'],request['rows']);owner=self.owner(agent)
        owner.lifetime.signal.throwIfAborted();self.requireOpen(owner,identity)
        if identity in owner.terminals:return owner.terminals[identity].info
        if identity in owner.pending:
            terminal=await asyncio.shield(owner.pending[identity]);self.requireOpen(owner,identity);return terminal.info
        self.requireCapacity(owner)
        return (await asyncio.shield(self.allocate(agent,owner,identity,lambda launch:self.userLaunch(agent,request,launch),signal))).info

    async def openForAgent(self,agent,request,signal):
        self.lifetime.signal.throwIfAborted();checked=title(request['title'])
        self.dimensions(request['cols'],request['rows']);owner=self.owner(agent)
        owner.lifetime.signal.throwIfAborted();self.requireCapacity(owner)
        controlled=set(owner.agentPending)
        for value in list(owner.terminals.values())+list(owner.allocations.values()):
            info=value.info
            if info['origin']=='agent' and info['control']=='agent' and info['state']=='running':controlled.add(info['id'])
        if len(controlled)>=self.config['maxAgentTerminals']:
            raise RemoteError('terminal/limit-reached','Session Agent terminal limit reached',dict(limit=self.config['maxAgentTerminals']))
        identity=str(uuid.uuid4());owner.agentPending.add(identity)
        launch=dict(request,title=checked)
        allocation=self.allocate(agent,owner,identity,lambda signal:self.agentLaunch(agent,identity,launch,signal),signal)
        allocation.add_done_callback(lambda _:owner.agentPending.discard(identity))
        terminal=await asyncio.shield(allocation)
        return AgentTerminalHandle(terminal,lambda:self.close(agent,identity))

    async def readScreen(self,agent,identity,request):
        terminal=self.terminal(agent,identity);await terminal.drain()
        if terminal.screenReleased:raise RemoteError('terminal/unavailable','Terminal was closed in this Session',{})
        return terminal.readScreen(request)

    async def inspectActivity(self,agent,identity):return await self.terminal(agent,identity).inspectActivity()

    @Remote(dict(mode='stream'))
    async def watch(self,sessionId,signal):
        dirty=True;waiting=None
        def changed(*_):
            nonlocal dirty
            dirty=True
            if waiting is not None and not waiting.done():waiting.set_result(None)
        listeners=self.rosters.setdefault(sessionId,set());listeners.add(changed)
        signals=(signal,self.lifetime.signal)
        for item in signals:item.addEventListener('abort',changed,dict(once=True))
        try:
            while not any(item.aborted for item in signals):
                if dirty:dirty=False;yield self.list(sessionId);continue
                waiting=asyncio.get_running_loop().create_future();await waiting;waiting=None
        finally:
            for item in signals:item.removeEventListener('abort',changed)
            listeners.discard(changed)
            if not listeners:self.rosters.pop(sessionId,None)

    @Remote(dict(mode='stream'))
    def retain(self,sessionId,identity,signal):
        owner=self.owners.get(sessionId);terminal=owner.terminals.get(identity) if owner is not None else None
        if terminal is None or identity in owner.closedIds or owner.lifetime.signal.aborted:
            raise RemoteError('terminal/unavailable','Terminal is closing or unavailable',{})
        return terminal.retain(signal)

    @Remote(dict(mode='stream'))
    def attach(self,agent,identity,signal):
        invocation=self.ctx.get('invocation')
        if invocation is None:raise RuntimeError('Terminal attachment requires a Remote invocation')
        return self.terminal(agent,identity).attach(invocation.uplink(),self.config,signal,invocation.uplinkWindow)

    @Remote
    def rename(self,agent,identity,value):
        checked=title(value);self.terminal(agent,identity).rename(checked)

    @Remote
    async def close(self,agent,identity):
        owner=self.owner(agent);owner.closedIds.add(identity)
        pending=owner.pending.get(identity)
        if pending is not None:
            try:await asyncio.shield(pending)
            except Exception:pass
        terminal=owner.terminals.get(identity)
        if terminal is not None:
            await terminal.close();owner.terminals.pop(identity,None)
        else:
            allocation=owner.allocations.get(identity)
            if allocation is None:return
            await allocation.cleanup.close();owner.allocations.pop(identity,None)
        self.changed(agent.id)

    def owner(self,agent):
        owner=self.owners.get(agent.id)
        if owner is None:
            owner=SimpleNamespace(terminals={},pending={},allocations={},closedIds=set(),lifetime=AbortController(),agentPending=set(),cleanup=None)
            self.owners[agent.id]=owner
            agent.ctx.effect(lambda:lambda:self.disposeOwner(agent.id,owner),'terminal-controller.owner')
        return owner

    def disposeOwner(self,identity,owner):
        if owner.cleanup is None:
            owner.lifetime.abort(RuntimeError('Terminal Session owner disposed'))
            async def cleanup():
                try:
                    await asyncio.gather(*list(owner.pending.values()),return_exceptions=True)
                    await settle([value.dispose() for value in owner.terminals.values()]+[value.cleanup.dispose() for value in owner.allocations.values()],'Session terminal cleanup failed')
                    owner.terminals.clear();owner.allocations.clear();self.owners.pop(identity,None);self.changed(identity)
                except Exception:owner.cleanup=None;raise
            owner.cleanup=CleanupPromise(cleanup())
        return owner.cleanup

    def changed(self,identity):
        for listener in list(self.rosters.get(identity,())):listener()

    def requireCapacity(self,owner):
        if len(set(owner.terminals)|set(owner.pending)|set(owner.allocations))>=self.config['maxTerminals']:
            raise RemoteError('terminal/limit-reached','Session terminal limit reached',dict(limit=self.config['maxTerminals']))

    def allocate(self,agent,owner,identity,prepare,signal):
        combined=AbortController();unsubscribers=[]
        for item in (signal,self.lifetime.signal,owner.lifetime.signal):
            unsubscribers.append(subscribe_abort(item,lambda reason:combined.abort(reason)))
        async def allocation():
            try:
                terminal=await self.spawn(agent,owner,identity,prepare,combined.signal)
                owner.terminals[identity]=terminal;owner.allocations.pop(identity,None)
                def closing():owner.closedIds.add(identity)
                def closed():owner.terminals.pop(identity,None);self.changed(agent.id)
                terminal.monitor(self.config,closing,closed,lambda error:self.ctx.logger.error('Browser terminal cleanup failed',error))
                terminal.setStateListener(lambda:self.changed(agent.id));self.changed(agent.id)
                self.requireOpen(owner,identity);return terminal
            finally:
                owner.pending.pop(identity,None)
                for unsubscribe in unsubscribers:unsubscribe()
        task=asyncio.ensure_future(allocation());task.add_done_callback(consume);owner.pending[identity]=task
        return task

    async def userLaunch(self,agent,request,signal):
        subprocess,_,directory=self.execution(agent);cwd=await directory.ensure(agent,signal)
        shell=await resolve_shell(subprocess,self.config.get('shell'),signal) if 'shellPath' not in request else next((shell for shell in await self.shells(agent,signal) if shell['path']==request['shellPath']),None)
        if shell is None:raise ValueError('Selected shell is not available in this execution environment')
        return dict(argv=[shell['path']]+shell['args'],env=dict(DSH_SESSION_ID=agent.id),
            info=dict(id=request['id'],shell=shell,title=shell['name'],cwd=cwd,cols=request['cols'],rows=request['rows'],state='running',exitCode=None,origin='user',control='user'))

    async def agentLaunch(self,agent,identity,request,signal):
        subprocess,_,directory=self.execution(agent)
        cwd=request.get('cwd')
        if cwd is None:cwd=await directory.ensure(agent,signal)
        shell=await self.agentShell(agent,request['preferredShells'],signal)
        argv=await self.confine(agent,[shell['path']]+shell['args'],request['policy'],signal)
        platform=(await subprocess.terminalEnvironment(signal))['platform'];mode=request['policy']['mode']
        history_file='/tmp/dsh-agent-history-'+identity;keeps=platform=='posix' and mode=='workspace-write'
        env=dict(request.get('env') or {},DSH_SESSION_ID=agent.id)
        if platform=='posix' and mode!='danger-full-access':env['HISTFILE']=history_file if keeps else ''
        launch=dict(argv=argv,env=env,info=dict(id=identity,shell=shell,title=request['title'],cwd=cwd,
            cols=request['cols'],rows=request['rows'],state='running',exitCode=None,origin='agent',control='agent',sandboxMode=mode))
        if keeps:launch['release']=lambda:self.removeHistory(subprocess,history_file)
        return launch

    async def removeHistory(self,subprocess,path):
        try:
            handle=subprocess.spawn(dict(argv=['rm','-f','--',path],cwd='/',stdio=dict(stdin='ignore',stdout=dict(maxBytes=4096),stderr=dict(maxBytes=4096)),graceMs=self.config['disposeGraceMs']))
            if inspect.isawaitable(handle):handle=await handle
            result=await asyncio.shield(handle.done)
            if result['exitCode']!=0:raise RuntimeError('rm ended with '+str(result.get('exitCode') if result.get('exitCode') is not None else result.get('signal')))
        except Exception as error:self.ctx.logger.warn('Agent terminal history cleanup failed',dict(path=path,error=error))

    async def agentShell(self,agent,preferred,signal):
        if preferred:
            shells=await self.shells(agent,signal)
            for name in preferred:
                shell=find_shell(shells,name)
                if shell is not None:return shell
        return await resolve_shell(self.execution(agent)[0],self.config.get('shell'),signal)

    async def confine(self,agent,argv,policy,signal):
        if policy['mode']=='danger-full-access':return argv
        sandbox=agent.ctx.get('sandbox')
        if sandbox is None:raise RuntimeError('Agent terminals in sandbox mode "'+policy['mode']+'" require a sandbox provider in the execution environment')
        result=sandbox.confine(argv,dict(policy,mode=policy['mode']),signal)
        if inspect.isawaitable(result):result=await result
        return result['argv']

    def terminal(self,agent,identity):
        owner=self.owners.get(agent.id);terminal=owner.terminals.get(identity) if owner is not None else None
        if terminal is None:raise RemoteError('terminal/unavailable','Terminal no longer exists in this Session',{})
        self.requireOpen(owner,identity);return terminal

    def requireOpen(self,owner,identity):
        if identity in owner.closedIds:raise RemoteError('terminal/unavailable','Terminal was closed in this Session',{})

    def dimensions(self,cols,rows):
        if not safe(cols) or not 2<=cols<=self.config['maxCols'] or not safe(rows) or not 1<=rows<=self.config['maxRows']:
            raise ValueError('Terminal dimensions exceed the configured limits')

    def execution(self,agent):
        subprocess,policy,directory=(agent.ctx.get(key) for key in ('subprocess','sandboxPolicy','workingDirectory'))
        if subprocess is None or policy is None:raise RuntimeError('The Session execution environment requires subprocess and sandbox policy providers')
        if directory is None:raise RuntimeError('The Session execution environment requires a working-directory provider')
        return subprocess,policy,directory

    async def spawn(self,agent,owner,identity,prepare,signal):
        launch=await prepare(signal);info=launch['info'];release=launch.get('release');screen=None
        handle=await self.execution(agent)[0].spawnTerminal(dict(argv=launch['argv'],cwd=info['cwd'],cols=info['cols'],rows=info['rows'],
            terminalType='xterm-256color',env=launch['env'],shellActivity=True,graceMs=self.config['disposeGraceMs'],signal=signal))
        try:
            signal.throwIfAborted()
            screen=await self.ctx.get('terminalScreens').open(dict(cols=info['cols'],rows=info['rows'],scrollback=self.config['scrollback']))
            signal.throwIfAborted()
            return BrowserTerminal(handle,info,screen,self.config['maxBufferedBytes'],release)
        except BaseException as error:
            async def terminate():
                owner.closedIds.add(identity);await handle.terminate()
                if screen is not None:await screen.dispose()
                if release is not None:await release()
                owner.allocations.pop(identity,None);self.changed(agent.id)
            cleanup=TerminalRetention(self.config,handle.inspectActivity,terminate,lambda error:self.ctx.logger.error('Browser terminal allocation cleanup failed',error))
            owner.allocations[identity]=SimpleNamespace(info=dict(info,state='failed',error=str(error)),cleanup=cleanup);self.changed(agent.id)
            try:await cleanup.close()
            except Exception as cleanup_error:raise AggregateError([error,cleanup_error],'Terminal allocation cleanup failed')
            raise
