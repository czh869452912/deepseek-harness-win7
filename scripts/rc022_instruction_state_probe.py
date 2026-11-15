"""Actual Session surfaces and FsLocal instruction reconciliation transitions."""
import json
from pathlib import Path
import sys
from weakref import WeakKeyDictionary
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.context.agent_instructions import state_authorized as state, config_authorized as config
    base=(workspace or WORKSPACE)/'native';project=base/'project';home=base/'home';shared=base/'shared';nested=project/'pkg'
    for path in (project,home,shared,nested):path.mkdir(parents=True,exist_ok=True)
    def write(path,text):path.write_bytes(text.encode('utf-8'))
    write(project/'.git','marker');write(home/'AGENTS.md','global');write(shared/'AGENTS.md',' global ')
    write(project/'AGENTS.md','first');write(project/'CLAUDE.md','second');write(nested/'AGENTS.md','nested')
    fixture=await setup(base/'sessions',directory=project);ctx=fixture.ctx;rows=[];handle=None
    try:
        handle=await ctx.agents.create(dict(sessionId='instructions',meta=dict(cwd=str(project)),agentOptions=dict(provider='script',model='model')))
        agent=handle.agent;filesystem=ctx.fs;cache=WeakKeyDictionary();reads=[];fail=set()
        original_stream=filesystem.streamText;original_stat=filesystem.stat
        async def stream(target,*args):reads.append(str(target));return await original_stream(target,*args)
        async def stat(target,*args):
            if filesystem.processPath(target) in fail:raise OSError('controlled unavailable')
            return await original_stat(target,*args)
        filesystem.streamText=stream;filesystem.stat=stat
        resolved=dict(config.resolve_config(dict(maxBytes=65536,maxSourceBytes=128)),dshHome=str(home),agentsHome=str(shared),localInstructionFileCandidates=[])
        options=dict(cwd=str(project),projectRoot=str(project),authorityMessages=[],scopeMessages=[],touchedPaths=[str(nested/'file.txt')],includeBaselineScopes=True,signal=fixture.signal)
        def clean(value):
            if isinstance(value,dict):return {key:('<opaque-version>' if key=='version' else clean(item)) for key,item in value.items() if key!='id'}
            if isinstance(value,(list,tuple)):return [clean(item) for item in value]
            return value
        async def run(name,settings=None,opts=None,commit=True):
            reads.clear();result=await state.reconcile_instruction_context(agent,settings or resolved,cache,filesystem,dict(options,**(opts or {})))
            rows.append(dict(name=name,result=clean(result),reads=len(reads),cache=clean(cache.get(agent.session,{}))))
            if result is not None and commit:
                state.apply_instruction_version_updates(agent.session,result['versionUpdates'],cache)
                agent.session.append('user/message',result['context'],surface_op='append')
            return result
        await run('initial')
        await run('warm')
        write(project/'AGENTS.md',' second ');await run('deduplicate-visible')
        await run('hidden-duplicate-fast-path')
        (project/'AGENTS.md').unlink();await run('promote-hidden-sibling')
        write(project/'CLAUDE.md','second');await run('same-digest-new-version')
        write(project/'AGENTS.md','recreated first');write(project/'CLAUDE.md','x'*129)
        write(home/'AGENTS.md','global independently changed');await run('oversized-group-rollback')
        write(project/'CLAUDE.md','second recovered');fail.add(str(project/'CLAUDE.md'))
        await run('unavailable-group-rollback');fail.clear()
        await run('recovered-group')
        await run('excluded-baseline',opts=dict(excludedBaselineScopes={'.\0AGENTS.md'}))
        claimed=state.agent_instructions_message('claimed',[dict(action='remove',scope='pkg\0AGENTS.md',path='pkg\\AGENTS.md')])
        await run('claimed-overrides-surface',opts=dict(authorityMessages=[claimed],includeBaselineScopes=False))
        write(nested/'CLAUDE.md','new hinted sibling')
        hint=state.agent_instructions_message('pending',[dict(action='set',scope='pkg\0CLAUDE.md',path='pkg\\CLAUDE.md')])
        await run('pending-scope-hint',opts=dict(scopeMessages=[hint],touchedPaths=[],includeBaselineScopes=False))
        write(nested/'AGENTS.md','new content to retry after tiny rendering budget')
        await run('notice-only-budget',settings=dict(resolved,maxBytes=3),commit=False)
        await run('retry-after-budget')
        files=[dict(absolutePath='one',displayPath='AGENTS.md',content='\ufeff😀value\x1c'),dict(absolutePath='two',displayPath='pkg\\AGENTS.md',content=' nested ',version='known')]
        rows.append(dict(name='baseline-state',value=clean(state.baseline_instruction_state(files))))
        change=dict(action='remove',scope='x',path='x');updates=[dict(change=change),dict(change=dict(change,action='set',digest='a'))]
        rows.append(dict(name='retained-updates',value=state.retained_instruction_version_updates(updates,[dict(change,ignored=True)])))
        return rows
    finally:
        if handle is not None:await handle.dispose()
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_instruction_state.mts','Actual Session surface plus local FS reconciliations; exact message content/source, deferred metadata transitions, cache fast paths and rollback. IDs omitted and physical-file versions projected to opaque tokens; no runtime event hook acceptance.',
        [Path(__file__).resolve()]+[ROOT/path for path in ('dsh/context/agent_instructions/state_authorized.py','dsh/context/agent_instructions/files_authorized.py','dsh/context/agent_instructions/render_authorized.py')],prepare=prepare)
