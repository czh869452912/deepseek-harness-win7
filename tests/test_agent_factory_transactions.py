"""Source-derived factory boundary probes; real registries/scopes, gated storage."""
import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.session.preparation import SessionPreparation
from dsh.core.abort import AbortController
from dsh.session.persistence import SessionInspection
from types import SimpleNamespace


class Storage:
    def __init__(self, ctx):
        self.session = ctx.get('sessions').prepare('restored')
        self.releases = 0

    async def load(self, sid):
        return SessionInspection(self.session.header, [])

    async def prepare(self, sid, signal=None):
        return SessionPreparation.create(self.session, {'release': self.release})

    def release(self):
        self.releases += 1


def harness():
    ctx = Context()
    SessionPlugin().apply(ctx)
    AgentPlugin().apply(ctx)
    AgentLoopPlugin().apply(ctx)
    storage = Storage(ctx)
    ctx.set_service('session_persistence', storage)
    return ctx, storage


@pytest.mark.asyncio
async def test_resume_setup_is_unpublished_and_uses_exact_preparation():
    ctx, storage = harness()
    entered, release = asyncio.Event(), asyncio.Event()
    observations = []
    for event in ('session/created', 'agent/created', 'agent/session-start'):
        ctx.on(event, lambda *args, event=event: observations.append(event))
    async def setup(scope):
        entered.set()
        await release.wait()
    job = asyncio.create_task(ctx.get('agents').resume({'resumeSessionId': 'restored', 'setup': setup}))
    handle = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert ctx.get('sessions').get('restored') is None
        assert ctx.get('agents').get('restored') is None
        assert observations == []
        release.set()
        handle = await job
        assert handle.agent.session is storage.session
        assert observations == ['session/created', 'agent/created', 'agent/session-start']
        assert storage.releases == 1
    finally:
        release.set()
        if handle is None:
            handle = await job
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_rejected_setup_never_publishes_and_releases_preparation():
    ctx, storage = harness()
    seen = []
    ctx.on('session/created', lambda *args: seen.append('published'))
    def setup(scope):
        raise ValueError('setup failed')
    try:
        with pytest.raises(ValueError, match='setup failed'):
            await ctx.get('agents').resume({'resumeSessionId': 'restored', 'setup': setup})
        assert seen == []
        assert storage.releases == 1
        assert ctx.get('sessions').get('restored') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_registry_forwards_pre_aborted_signal_without_starting_setup():
    ctx, storage = harness()
    controller = AbortController()
    error = RuntimeError('caller stopped')
    controller.abort(error)
    seen = []
    try:
        with pytest.raises(RuntimeError, match='caller stopped') as raised:
            await ctx.get('agents').create({'sessionId': 'aborted', 'signal': controller.signal,
                                           'setup': lambda scope: seen.append('setup')})
        assert raised.value is error
        assert seen == []
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['load', 'setup'])
@pytest.mark.parametrize('source', ['caller', 'owner', 'factory', 'observer'])
async def test_cancellation_settles_promptly_and_late_values_cannot_publish(phase, source):
    ctx, storage = harness()
    owner = ctx.plugin(lambda scope: None)
    await owner
    started, late = asyncio.Event(), asyncio.get_running_loop().create_future()
    caller = AbortController()
    seen = []
    ctx.on('session/created', lambda *args: seen.append('session'))
    async def prepare(sid, signal):
        started.set()
        await late
        return SessionPreparation.create(storage.session, storage.release)
    async def setup(scope):
        started.set()
        await late
        return SimpleNamespace(commit=lambda: seen.append('commit'))
    if phase == 'load':
        storage.prepare = prepare
    job = asyncio.create_task(owner.ctx.get('agents').resume({
        'resumeSessionId': 'restored', 'signal': caller.signal,
        'setup': setup if phase == 'setup' else None}))
    await asyncio.wait_for(started.wait(), 1)
    try:
        if source == 'caller':
            caller.abort(RuntimeError('caller stopped'))
        elif source == 'owner':
            await asyncio.wait_for(owner.dispose(), 1)
        elif source == 'factory':
            await asyncio.wait_for(ctx.get('agent_loop').teardown(), 1)
        else:
            job.cancel()
        with pytest.raises((RuntimeError, asyncio.CancelledError)):
            await asyncio.wait_for(job, 1)
        assert seen == []
        assert ctx.get('sessions').get('restored') is None
        if source != 'factory':
            replacement = await ctx.get('agents').create('restored')
        else:
            replacement = None
        late.set_result(None)
        for _ in range(5):
            await asyncio.sleep(0)
        assert storage.releases == 1
        assert 'commit' not in seen
        if replacement:
            assert ctx.get('agents').get('restored') is replacement.agent
            await replacement.dispose()
    finally:
        if not late.done():
            late.set_result(None)
        await asyncio.gather(job, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_seed_owner_publication_and_idempotent_dispose():
    ctx, _ = harness()
    parent = await ctx.get('agents').create('parent')
    seed = [{'type':'turn/start','seq':0,'time':1,'data':{'turn':1}},
            {'type':'turn/end','seq':1,'time':2,'data':{'turn':1,'reason':{'kind':'completed'}}}]
    child = await parent.agent.ctx.get('agents').create({'sessionId':'child','seed':seed})
    try:
        assert ctx.get('agents').is_owned_by('child', parent.agent)
        assert list(child.agent.session.events)[:2] == seed
        assert child.agent.session.events[2]['type'] == 'session/end-seed'
        await asyncio.gather(child.dispose(), child.dispose())
        assert ctx.get('agents').get('child') is None
        assert ctx.get('sessions').get('child') is None
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_commit_failure_is_unpublished_and_identity_is_reusable():
    ctx, storage = harness()
    seen = []
    ctx.on('session/created', lambda *args: seen.append('published'))
    def commit():
        raise ValueError('commit failed')
    try:
        with pytest.raises(ValueError, match='commit failed'):
            await ctx.get('agents').resume({'resumeSessionId':'restored',
                'setup':lambda scope: SimpleNamespace(commit=commit)})
        assert seen == [] and storage.releases == 1
        handle = await ctx.get('agents').create('restored')
        await handle.dispose()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_synchronous_setup_abort_prevents_commit():
    ctx, _ = harness()
    caller = AbortController()
    seen = []
    def setup(scope):
        caller.abort(RuntimeError('stop before commit'))
        return SimpleNamespace(commit=lambda: seen.append('commit'))
    try:
        with pytest.raises(RuntimeError, match='stop before commit'):
            await ctx.get('agents').create({'sessionId':'sync-abort','signal':caller.signal,'setup':setup})
        assert seen == [] and ctx.get('sessions').get('sync-abort') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_competing_creates_publish_one_identity_and_retire_owner_effects():
    ctx, _ = harness()
    owner = ctx.plugin(lambda scope: None)
    await owner
    before = len(owner._disposables)
    reached, release = asyncio.Event(), asyncio.Event()
    async def setup(scope):
        reached.set()
        await release.wait()
    loser = asyncio.create_task(owner.ctx.get('agents').create({'sessionId':'same','setup':setup}))
    await reached.wait()
    winner = await ctx.get('agents').create('same')
    try:
        release.set()
        with pytest.raises(ValueError, match='already exists'):
            await loser
        assert ctx.get('agents').get('same') is winner.agent
        assert len(owner._disposables) == before
        await winner.dispose()
        replacement = await owner.ctx.get('agents').create('same')
        await replacement.dispose()
        assert len(owner._disposables) == before
    finally:
        await winner.dispose()
        await ctx.fiber.dispose()
