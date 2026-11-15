"""Pair ordinary activation against real Agent, preset and journal providers."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from dsh.cordis.loader import Loader
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.presets.registry_current import CurrentAgentPresetRegistry
    from dsh.api.session_agents_authorized import AuthorizedSessionAgents
    from dsh.api.session_commands_authorized import AuthorizedSessionCommands
    from dsh.llm.message import create_user_message
    workspace = workspace or WORKSPACE
    fixture = await setup(workspace/'native')
    ctx, rows, requests = fixture.ctx, [], []
    defaults = dict(provider='record', model='initial')
    save_entered, release_save = asyncio.Event(), asyncio.Event()
    async def save(value):
        save_entered.set()
        await release_save.wait()
        defaults.clear(); defaults.update(value)
    class Recording(ScriptAdapter):
        async def list_models(self, provider, signal=None):
            return [dict(provider=provider, id=name, name=name) for name in ('initial', 'changed', 'selected')]
        async def stream(self, request):
            requests.append(dict(provider=request['provider'], model=request['model']))
            yield dict(type='block-start', index=0, blockType='text')
            yield dict(type='text-delta', index=0, text='done')
            yield dict(type='block-end', index=0, block=dict(type='text', text='done'))
            yield dict(type='finish', reason=dict(kind='stop'))
    try:
        await ctx.plugin(CurrentTypertRegistry)
        ctx.baseUrl=workspace.as_uri()+'/'
        await ctx.plugin(Loader)
        await ctx.plugin(CurrentAgentPresetRegistry, dict(default='coding'))
        for name in ('coding', 'reviewing'):
            await ctx.agentPresets.register(dict(id=name, plugins=[]))
        ctx.set_service('agentDefaultModel', NS(currentSelection=lambda:dict(defaults), saveSelection=save))
        ctx.llm.registerAdapter(['record'], Recording({}))
        archived, members, attached = [], ['blank'], []
        async def attach(identity):
            attached.append(identity)
            if identity not in members: members.append(identity)
        workspace_entity=NS(id='work', path=str(workspace/'project'), sessionIds=members, attachSession=attach)
        ctx.set_service('workspaceRegistry', NS(get=lambda identity:workspace_entity if identity=='work' else None, archivedSessionIds=archived))
        agents=AuthorizedSessionAgents(ctx)
        commands=AuthorizedSessionCommands(ctx, agents, workspace_entity.path)
        await commands.initialize()
        async def create(name, **extra):
            result=await commands.create(dict(sessionId=name, **extra))
            return result, ctx.agents.get(result['sessionId'])
        first, blank=await create('blank', workspaceId='work')
        rows.append(dict(name='fresh', named=blank.id=='blank', preset=first['agentPreset'], model=blank.model.current()))
        defaults['model']='changed'
        rows.append(dict(name='dynamic-default', model=blank.model.current()))
        switched, same=await create('blank', workspaceId='work', agentPreset='reviewing')
        rows.append(dict(name='reuse-select', same=same is blank, preset=switched['agentPreset'], selections=[event['data']['agentPreset'] for event in blank.session.snapshotEvents() if event['type']=='agent-preset/selected']))
        selected=await asyncio.gather(create('blank', workspaceId='work', agentPreset='coding'), create('blank', workspaceId='work', agentPreset='reviewing'))
        rows.append(dict(name='ordered-claims', same=all(agent is blank for _,agent in selected), presets=[result['agentPreset'] for result,_ in selected], final=ctx.agentPresets.presetForSession(blank.session)))
        omitted, same=await create('blank', workspaceId='work')
        rows.append(dict(name='omitted-default', same=same is blank, preset=omitted['agentPreset']))
        for label, request in [('cwd-before-preset', dict(cwd=str(workspace/'wrong'), agentPreset='missing')), ('missing-preset', dict(agentPreset='missing')), ('missing-workspace', dict(workspaceId='missing')), ('both-locations', dict(workspaceId='work', cwd=workspace_entity.path))]:
            try: await commands.create(dict(sessionId='blank', **request))
            except Exception as error: rows.append(dict(name=label, code=error.code))
        await commands.selectModel(dict(sessionId='blank', provider='record', model='selected'))
        await save_entered.wait()
        before=blank.session.seq
        await commands.selectModel(dict(sessionId='blank', provider='record', model='selected'))
        rows.append(dict(name='selected-before-save', savePending=not release_save.is_set(), duplicateSkipped=blank.session.seq==before, current=blank.model.current(), projection=ctx.sessionProjections.snapshot(blank.session)['values']['modelSelection']))
        try: await commands.selectModel(dict(sessionId='blank', provider='record', model='absent'))
        except Exception as error: rows.append(dict(name='unavailable-model', code=error.code, current=blank.model.current()))
        blank.followup(create_user_message(dict(content=[dict(type='text', text='task')], source=dict(kind='user'))))
        await blank.whenIdle()
        rows.append(dict(name='actual-request', requests=requests, projection=ctx.sessionProjections.snapshot(blank.session)['values']['modelSelection']))
        started, replacement=await create('blank', workspaceId='work')
        rows.append(dict(name='started-mints', minted=replacement.id!='blank', attached=attached[-1]==replacement.id, preset=started['agentPreset']))
        archived.append(replacement.id)
        _, unarchived=await create(replacement.id, workspaceId='work')
        rows.append(dict(name='archived-mints', minted=unarchived.id!=replacement.id))
        _, outsider=await create('outsider')
        _, placed=await create('outsider', workspaceId='work')
        rows.append(dict(name='placement-mints', minted=placed is not outsider))
        composition=await agents.composeAgent('reviewing')
        cold=await ctx.agents.create(dict(sessionId='cold', meta=dict(cwd=workspace_entity.path, agentPreset='reviewing'), agentOptions=agents.agent_options(), setup=composition['setup']))
        await cold.dispose()
        result, resumed=await create('cold', agentPreset='coding')
        rows.append(dict(name='cold-blank-reuse', named=resumed.id=='cold', preset=result['agentPreset'], selections=[event['data']['agentPreset'] for event in resumed.session.snapshotEvents() if event['type']=='agent-preset/selected']))
        cold_started=await ctx.agents.create(dict(sessionId='cold-started', meta=dict(cwd=workspace_entity.path), agentOptions=agents.agent_options()))
        cold_started.agent.session.append('turn/start', dict(turn=1))
        await cold_started.dispose()
        _, fresh=await create('cold-started')
        rows.append(dict(name='cold-started-mints', minted=fresh.id!='cold-started', oldAgentAbsent=ctx.agents.get('cold-started') is None))
        child=await ctx.agents.create(dict(sessionId='child', meta=dict(cwd=workspace_entity.path, origin='subagent'), agentOptions=agents.agent_options()))
        try: await create('child', agentPreset='missing')
        except Exception as error: rows.append(dict(name='child-before-preset', code=error.code))
        release_save.set(); await commands.drain_default_saves()
        rows.append(dict(name='settled', claims=len(agents.claims), saves=len(commands.default_saves), default=dict(defaults)))
        return json.loads(json.dumps(rows))
    finally:
        release_save.set()
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files'; WORKSPACE.mkdir()
    path=output/'workspace.json'; path.write_text(json.dumps(str(WORKSPACE)), encoding='utf-8')
    return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_activation.mts', 'Actual Agent/Session/projection/preset/Loader/JSONL/query providers and ordinary activation/commands: ordered blank reuse, explicit/default preset changes, started/archived/foreign-workspace minting, cold reuse/refusal, identity error precedence, dynamic defaults, core model selection and background default save. Workspace membership and deployment-default persistence are controlled collaborators; full SessionController boot is separate.',
        [Path(__file__).resolve(), ROOT/'dsh/api/session_agents_authorized.py', ROOT/'dsh/api/session_commands_authorized.py', ROOT/'dsh/api/session_authorized.py', ROOT/'dsh/api/session_current.py'], prepare=prepare)

