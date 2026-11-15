import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.api.archived_session_gate import ArchivedSessionGate, under_archived_session
from dsh.api.session_authorized import AuthorizedSessionController
from dsh.cordis import Context
from dsh.core.session.current_session import CurrentSessionStore
from dsh.typert.current import CurrentTypertRegistry
from scripts.rc022_session_composition_probe import observe


@pytest.mark.asyncio
async def test_actual_controller_boot_interleaving_gateway_and_unload(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 8
    opening = rows['opening-captured-during-init']
    assert opening['baseline']['activeAttempt']['attemptId'] == 'boot-attempt'
    assert opening['budget'] == 4 and not opening['hasLegacyHistory']
    assert rows['state-through-gateway']['value']['active']
    assert rows['wait-through-gateway']['reason'] == 'idle' and rows['upload-resolver']['same']
    assert rows['availability-events']['value'] == [
        dict(type='added', sessionId='availability', agentAvailable=False),
        dict(type='added', sessionId='availability', agentAvailable=True),
        dict(type='added', sessionId='availability', agentAvailable=False),
        dict(type='removed', sessionId='availability')]
    assert rows['projection-control']['keys'] == ['projections']
    assert rows['archive-stops-model-step'] == dict(name='archive-stops-model-step', requests=0, ending=['blocked'])
    assert rows['unloaded'] == dict(name='unloaded', resolvers=0, newEvents=0, baselines=0, serviceGone=True)


@pytest.mark.parametrize('budget', [0, -1, .5, float('nan'), float('inf'), True])
def test_public_config_rejects_invalid_list_work_budget(budget):
    with pytest.raises(Exception): AuthorizedSessionController.Config(dict(listWorkSliceMs=budget))


@pytest.mark.asyncio
async def test_constructor_only_configures_native_inputs_before_init():
    ctx = Context()
    await ctx.plugin(CurrentTypertRegistry)
    try:
        assert AuthorizedSessionController.Config({})['listWorkSliceMs'] == 16
        api = AuthorizedSessionController(ctx, dict(nativeOpen=False, listWorkSliceMs=32))
        assert api.list_work_slice_ms == 32 and not api.canOpenWorkspacePath()
        assert not hasattr(api, 'history') and not hasattr(api, 'agents') and not hasattr(api, 'commands')
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_archive_gate_lineage_cycle_fork_missing_parent_and_unload():
    ctx = Context(); store = CurrentSessionStore(ctx, 4); archived = ['root', 'offline']
    ctx.set_service('agents', NS()); ctx.set_service('workspaceRegistry', NS(archivedSessionIds=archived))
    root = store.create('root'); child = store.create('child', dict(meta=dict(origin='subagent', parentSession='root')))
    grandchild = store.create('grandchild', dict(meta=dict(origin='subagent', parentSession='child')))
    fork = store.create('fork', dict(meta=dict(parentSession='root')))
    missing = store.create('missing', dict(meta=dict(origin='subagent', parentSession='offline')))
    cycle_a = store.create('cycle-a', dict(meta=dict(origin='subagent', parentSession='cycle-b')))
    store.create('cycle-b', dict(meta=dict(origin='subagent', parentSession='cycle-a')))
    provider = await ctx.plugin(ArchivedSessionGate)
    async def admitted(session): return await ctx.waterfall('agent/pre-step', dict(agent=NS(session=session)), lambda: dict(kind='enter'))
    try:
        for session in (root, child, grandchild, missing):
            assert await admitted(session) == dict(kind='reject')
        assert await admitted(fork) == dict(kind='enter')
        assert not under_archived_session(ctx, NS(session=cycle_a))
        archived.clear()
        assert await admitted(grandchild) == dict(kind='enter')
        archived.append('root'); await provider.dispose()
        assert await admitted(grandchild) == dict(kind='enter')
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_execution_resumes_after_unarchive(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from scripts.rc022_inbox_readers_probe import message
    fixture = await setup(tmp_path / 'journal'); ctx = fixture.ctx; archived = ['root']
    ctx.set_service('workspaceRegistry', NS(archivedSessionIds=archived))
    await ctx.plugin(ArchivedSessionGate)
    try:
        handle = await ctx.agents.create(dict(sessionId='root', meta=dict(cwd='C:/root'), agentOptions=dict(provider='script', model='model')))
        agent = handle.agent; agent.followup(message('blocked')); await asyncio.wait_for(agent.whenIdle(), 5)
        assert not any(event['type'] == 'request/header' for event in agent.session.snapshotEvents())
        archived.clear(); agent.followup(message('restored'))
        async def started():
            while not any(event['type'] == 'request/header' for event in agent.session.snapshotEvents()): await asyncio.sleep(0)
        await asyncio.wait_for(started(), 5)
        agent.cancel(); await asyncio.wait_for(agent.whenIdle(), 5)
        assert any(event['type'] == 'request/header' for event in agent.session.snapshotEvents())
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_pending_promotion_is_joined_at_provider_unload(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    from dsh.fs.fs_local import FsLocalPlugin
    from dsh.api.session_agents_authorized import AuthorizedSessionAgents
    fixture = await setup(tmp_path / 'journal'); ctx = fixture.ctx; resolver = []; entered = asyncio.Event(); release = asyncio.Event()
    for plugin in (CurrentTypertRegistry, RemoteAccessService, AuthorizedGatewayService): await ctx.plugin(plugin)
    await ctx.plugin(FsLocalPlugin, dict(cwd=str(tmp_path)))
    ctx.set_service('agentDefaultModel', NS(currentSelection=lambda: dict(provider='script', model='model')))
    ctx.set_service('attachments', NS(imageLimits=dict(maxImageBytes=1,maxImagesPerMessage=1,maxMessageImageBytes=1,maxImagePixels=1,maxImageDimension=1,mediaTypes=[])))
    ctx.set_service('workspaceRegistry', NS(archivedSessionIds=[]))
    def register(callback):
        resolver.append(callback)
        return lambda: resolver.remove(callback)
    ctx.set_service('fileUploads', NS(registerAgentResolver=register))
    released = []
    class HeldAgents(AuthorizedSessionAgents):
        async def resolveObservedAgent(self, observation):
            entered.set(); await release.wait()
            return dict(error=RuntimeError('activation failed'))
    class Controller(AuthorizedSessionController): agents_class = HeldAgents
    provider = await ctx.plugin(Controller, dict(nativeOpen=False)); api = ctx.sessionController
    try:
        api.promote(NS(header=NS(id='held'), dispose=lambda: released.append(True)))
        await entered.wait(); closing = asyncio.ensure_future(provider.dispose()); await asyncio.sleep(0)
        assert not closing.done()
        release.set(); await closing
        assert released == [True] and not api.promotions and not resolver
    finally:
        release.set(); await provider.dispose(); await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_async_initialization_unwinds_owned_registrations(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    from dsh.fs.fs_local import FsLocalPlugin
    from dsh.api.session_commands_authorized import AuthorizedSessionCommands
    fixture = await setup(tmp_path / 'journal'); ctx = fixture.ctx; resolver = []; captured = []; primary = RuntimeError('initialization failed')
    for plugin in (CurrentTypertRegistry, RemoteAccessService, AuthorizedGatewayService): await ctx.plugin(plugin)
    await ctx.plugin(FsLocalPlugin, dict(cwd=str(tmp_path)))
    ctx.set_service('agentDefaultModel', NS(currentSelection=lambda: dict(provider='script', model='model')))
    ctx.set_service('attachments', NS(imageLimits={}))
    ctx.set_service('workspaceRegistry', NS(archivedSessionIds=[]))
    def register(callback):
        resolver.append(callback)
        return lambda: resolver.remove(callback)
    ctx.set_service('fileUploads', NS(registerAgentResolver=register))
    class BrokenCommands(AuthorizedSessionCommands):
        async def initialize(self):
            await super().initialize()
            await asyncio.sleep(0)
            raise primary
    class Controller(AuthorizedSessionController):
        commands_class = BrokenCommands
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); captured.append(self)
    pending = ctx.plugin(Controller, dict(nativeOpen=False))
    try:
        with pytest.raises(RuntimeError) as caught: await pending
        assert caught.value is primary
        await pending.dispose()
        assert not resolver and ctx.get('sessionController') is None
        session = ctx.sessions.create('after-failure')
        ctx.emit('agent/assistant-stream', dict(agent=NS(session=session), frame=dict(type='start',attemptId='late',revision=1,turn=1,step=1)))
        assert not captured[0].history_reads.streamsListener.streams
    finally:
        await pending.dispose(); await ctx.fiber.dispose()
