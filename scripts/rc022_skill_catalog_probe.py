"""Pair passive catalogs through actual Session, directory, skill and preset services."""
import asyncio
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.api.session_catalogs_authorized import AuthorizedSessionSkillCatalog
    from dsh.cordis.loader import Loader
    from dsh.presets.registry_current import CurrentAgentPresetRegistry
    from dsh.skill.registry import SkillRegistry
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.core.abort import AbortController
    base = workspace or WORKSPACE; directory = base/'native-work'; directory.mkdir()
    moved = directory/'moved'; moved.mkdir()
    fixture = await setup(base/'native', directory=directory); ctx = fixture.ctx; rows = []; calls = []
    try:
        for plugin in (CurrentTypertRegistry, SkillRegistry, Loader): await ctx.plugin(plugin)
        ctx.baseUrl = base.as_uri()+'/'
        def contribution(child, config):
            child.get('skills').register(dict(name=config['name'], description='Preset skill', source='test', content='instructions', path='/virtual/SKILL.md',
                whenToUse='Review', invocation=dict(modelInvocable=False, userInvocable=True)))
        contribution.inject = ['skills']
        ctx.loader.builtins['contribute'] = contribution
        await ctx.plugin(CurrentAgentPresetRegistry, dict(default='coding')); presets = ctx.agentPresets
        def definition(name): return dict(id='coding', plugins=[dict(id='skills', name='cordis:contribute', config=dict(name=name))])
        unregister = await presets.register(definition('review'))
        ctx.skills.register(dict(name='global', description='Global skill', source='test', content='instructions', invocation=dict(modelInvocable=True, userInvocable=True)))
        ctx.skills.register(dict(name='hidden', description='Model only', source='test', content='instructions', invocation=dict(modelInvocable=True, userInvocable=False)))
        catalog = AuthorizedSessionSkillCatalog(ctx)
        original = ctx.skills.list
        async def listing(options):
            calls.append(dict(cwd='moved' if options['cwd']==str(moved) else 'default' if options['cwd']==str(directory) else options['cwd'],
                              scope='live' if hasattr(options.get('scope'), 'session') else 'standing' if options.get('scope') is not None else 'global'))
            return await original(options)
        ctx.skills.list = listing
        session = ctx.sessions.create('cold', dict(meta=dict(cwd=str(directory), agentPreset='coding')))
        session.append('working-directory/change', dict(cwd=str(moved)))
        rows.append(dict(name='cold-projected', value=await catalog.list(dict(sessionId='cold'), fixture.signal), call=calls[-1], agents=len(ctx.agents.list())))
        ctx.sessions.create('default')
        aborted = AbortController(); aborted.abort()
        rows.append(dict(name='cold-default-admitted-cancel', value=await catalog.list(dict(sessionId='default'), aborted.signal), call=calls[-1]))
        ctx.sessions.create('unknown', dict(meta=dict(cwd='/offline', agentPreset='absent')))
        rows.append(dict(name='unknown-preset-offline', value=await catalog.list(dict(sessionId='unknown'), fixture.signal), call=calls[-1]))
        async def composed(child, agent): await presets.mount(child, 'coding')
        handle = await ctx.agents.create(dict(sessionId='live', meta=dict(cwd=str(directory)), agentOptions=dict(provider='script',model='model'), setup=composed))
        await ctx.workingDirectory.set(handle.agent, str(moved), fixture.signal)
        rows.append(dict(name='live-directory', value=await catalog.list(dict(sessionId='live'),fixture.signal), call=calls[-1]))
        await handle.dispose()
        rows.append(dict(name='persisted-directory', value=await catalog.list(dict(sessionId='live'), fixture.signal), call=calls[-1], agents=len(ctx.agents.list())))
        gate, entered = asyncio.Event(), asyncio.Event()
        async def delayed(options): entered.set(); await gate.wait(); return await listing(options)
        ctx.skills.list = delayed
        pending = asyncio.ensure_future(catalog.list(dict(sessionId='cold'),fixture.signal)); await entered.wait()
        await unregister(); replacement = await presets.register(definition('review-new'))
        rows.append(dict(name='retained-during-read', generations=[row['id'] for row in presets.inspectCompositions()]))
        gate.set(); rows.append(dict(name='retired-view', value=await pending))
        rows.append(dict(name='released-after-read', generations=[row['id'] for row in presets.inspectCompositions()]))
        ctx.skills.list = listing
        rows.append(dict(name='replacement-view', value=await catalog.list(dict(sessionId='cold'),fixture.signal)))
        async def failed(_): raise RuntimeError('catalog failed')
        ctx.skills.list = failed
        try: await catalog.list(dict(sessionId='cold'),fixture.signal)
        except Exception as error: rows.append(dict(name='listing-error', code=error.code, message=str(error)))
        await replacement()
        rows.append(dict(name='released-after-error', generations=[row['id'] for row in presets.inspectCompositions()]))
        try: await catalog.list(dict(sessionId='missing'),fixture.signal)
        except Exception as error: rows.append(dict(name='missing', code=error.code, details=error.details))
        return json.loads(json.dumps(rows))
    finally: await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files'; WORKSPACE.mkdir(); path=output/'workspace.json'; path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8'); return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_skill_catalog.mts', 'Actual Session/query/JSONL, WorkingDirectory/local FS, scoped SkillRegistry and declarative Loader presets: passive projected/default/offline directories, live directory coordination, persisted reads without activation, optional paths and invocation filtering, retained generations during async reads, replacement and failure release. The delayed/failed list wrapper is a controlled scheduling/failure boundary.',
        [Path(__file__).resolve(), ROOT/'dsh/api/session_catalogs_authorized.py', ROOT/'dsh/skill/registry.py'], prepare=prepare)
