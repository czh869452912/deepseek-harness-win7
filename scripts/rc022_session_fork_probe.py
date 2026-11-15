"""Pair exact fork cuts through actual Agent factories and durable observations."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from scripts.rc022_inbox_readers_probe import message
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from dsh.api.session_agents_authorized import AuthorizedSessionAgents
    from dsh.api.session_commands_authorized import AuthorizedSessionCommands
    from dsh.api.session_authorized import AuthorizedSessionController
    from dsh.session.jsonl_current import generationLogPath
    from dsh.core.session.plugin_records import appendPluginRecord
    from dsh.cordis.loader import Loader
    from dsh.presets.registry_current import CurrentAgentPresetRegistry
    from dsh.typert.current import CurrentTypertRegistry
    base=workspace or WORKSPACE;fixture=await setup(base/'native');ctx=fixture.ctx;rows=[];members=['source'];attached=[];requests=[]
    class Recording(ScriptAdapter):
        async def stream(self, request):
            requests.append(request)
            yield dict(type='block-start',index=0,blockType='text')
            yield dict(type='text-delta',index=0,text='done')
            yield dict(type='block-end',index=0,block=dict(type='text',text='done'))
            yield dict(type='finish',reason=dict(kind='stop'))
    try:
        for plugin in (CurrentTypertRegistry, Loader):await ctx.plugin(plugin)
        ctx.baseUrl=base.as_uri()+'/'
        await ctx.plugin(CurrentAgentPresetRegistry,dict(default='coding'));await ctx.agentPresets.register(dict(id='coding',plugins=[]))
        ctx.set_service('agentDefaultModel',NS(currentSelection=lambda:dict(provider='record',model='default')))
        ctx.llm.registerAdapter(['record'],Recording({}))
        async def attach(identity):members.append(identity);attached.append(identity)
        entity=NS(id='work',sessionIds=members,attachSession=attach)
        ctx.set_service('workspaceRegistry',NS(list=lambda:[entity],archivedSessionIds=[]))
        agents=AuthorizedSessionAgents(ctx);commands=AuthorizedSessionCommands(ctx,agents,'C:/fork');await commands.initialize()
        composition=await agents.composeAgent('coding')
        source_handle=await ctx.agents.create(dict(sessionId='source',meta=dict(cwd='C:/fork',agentPreset='coding'),agentOptions=dict(provider='record',model='original'),setup=composition['setup']))
        source=source_handle.agent.session
        source.append('turn/start',dict(turn=1));source.append('user/message',message('first'),'append');source.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
        appendPluginRecord(source,'plugin:fixture/checkpoint',dict(value='kept'))
        source.append('user/message',message('next'),'append')
        source.append('turn/start',dict(turn=2));source.append('step/start',dict(turn=2,step=1))
        source.append('assistant/message',dict(turn=2,step=1,stream=[],message=dict(id='assistant',role='assistant',source=dict(kind='model',provider='record',model='original'),content=[dict(type='tool-call',id=call,name='example',arguments='{}') for call in ('started','pending')])),'append')
        source.append('tool/call',dict(turn=2,step=1,callId='started',name='example',arguments='{}'))
        original=source.snapshotEvents();before=json.dumps(original)
        core=ctx.sessions.fork(source,8,'core-fork')
        rows.append(dict(name='core-open-fork',inherited=core.inheritedEventCount,types=[event['type'] for event in core.snapshotEvents()],parent=core.header.parentSession))
        empty=ctx.sessions.create('empty');empty_child=ctx.sessions.fork(empty,child_session_id='empty-fork')
        rows.append(dict(name='core-empty-fork',inherited=empty_child.inheritedEventCount,types=[event['type'] for event in empty_child.snapshotEvents()],parent=empty_child.header.parentSession))
        def value(child):
            events=json.loads(json.dumps(child.session.snapshotEvents()))
            for event in events:event['time']=0
            header=child.session.header
            return dict(inherited=child.session.inheritedEventCount,events=events,model=child.model.current(),preset=header.agentPreset,
                        origin=header.origin,parent=header.parentSession,workspace=child.id in members)
        children=[]
        for label,cut in [('default',None),('first-event',0.0),('closed',2),('checkpoint',3),('queued-input',4),('open-turn',5),('open-step',6),('unstarted-tools',7),('started-tool',8)]:
            created=await commands.fork(dict(sessionId='source',**({} if cut is None else dict(atSeq=cut))))
            child=ctx.agents.get(created['sessionId']);children.append(child)
            rows.append(dict(name=label,value=value(child)))
        for label,request in [('missing',dict(sessionId='missing')),('past-end',dict(sessionId='source',atSeq=999)),('invalid',dict(sessionId='source',atSeq=-0.0))]:
            try:await commands.fork(request)
            except Exception as error:rows.append(dict(name=label,code=error.code,message=str(error)))
        rows.append(dict(name='parent-unmodified',same=before==json.dumps(source.snapshotEvents()),attachments=len(attached)))
        child=children[-1];child.followup(message('continue fork'));await child.whenIdle()
        rows.append(dict(name='continued-actual-agent',provider=requests[-1]['provider'],model=requests[-1]['model'],forkResults=sum(event['type']=='tool/result' for event in child.session.snapshotEvents()),turnEnd=child.session.snapshotEvents()[-1]['data']['reason']['kind']))
        await source_handle.dispose()
        created=await commands.fork(dict(sessionId='source',atSeq=8))
        rows.append(dict(name='cold-exact',value=value(ctx.agents.get(created['sessionId'])),sourceInactive=ctx.agents.get('source') is None))
        historical=Path(generationLogPath(str(base/'native'),'C:/fork','historical',3,'none'));historical.parent.mkdir(parents=True,exist_ok=True)
        old_events=json.loads(before)[:3]
        header=dict(type='session',version=3,id='historical',createdAt=1,isSeeded=False,delegationDepth=0,cwd='C:/fork',agentPreset='coding')
        raw=''.join(json.dumps(row)+'\n' for row in [header]+old_events);historical.write_text(raw,encoding='utf-8')
        facade=NS(ctx=ctx,commands=commands)
        try:await AuthorizedSessionController.fork(facade,dict(sessionId='historical',allowMigration=False))
        except Exception as error:rows.append(dict(name='migration-refused',code=error.code,details=error.details))
        created=await AuthorizedSessionController.fork(facade,dict(sessionId='historical',allowMigration=True))
        rows.append(dict(name='migration-permitted-passive',value=value(ctx.agents.get(created['sessionId'])),sourceInactive=ctx.agents.get('historical') is None,
                         sourceUnchanged=historical.read_text(encoding='utf-8')==raw,sourceStatus=(await ctx.sessionPersistence.stat('historical'))['formatStatus']))
        return json.loads(json.dumps(rows))
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_fork.mts','Actual Agent/Session/query/JSONL, declarative preset and core model projections: omitted versus every exact boundary, inherited marker and fork closers, started/unstarted tool uncertainty, workspace attachment, independent lineage, unmodified parent, real continued generation and cold source without activation. Model adapter responses and workspace membership are controlled collaborators.',
        [Path(__file__).resolve(),ROOT/'dsh/core/session/fork.py',ROOT/'dsh/core/session/current_session.py',ROOT/'dsh/api/session_commands_authorized.py',ROOT/'dsh/api/session_authorized.py'],prepare=prepare)
