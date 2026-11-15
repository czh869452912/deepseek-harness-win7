import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.api.session_authorized import AuthorizedSessionController
from dsh.api.session_commands_authorized import AuthorizedSessionCommands, latest_completed_prefix_boundary
from dsh.cordis import Context


@pytest.mark.asyncio
async def test_actual_exact_live_cold_forks_and_migration_preflight(tmp_path):
    from scripts.rc022_session_fork_probe import observe
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert rows['core-open-fork']['inherited'] == 9 and rows['core-open-fork']['parent'] is None
    assert rows['core-open-fork']['types'][-5:] == ['session/end-seed', 'tool/result', 'tool/result', 'step/end', 'turn/end']
    assert rows['core-empty-fork'] == dict(name='core-empty-fork', inherited=0, types=['session/end-seed'], parent=None)
    assert rows['default']['value']['inherited'] == 4
    for name, cut in [('first-event', 0), ('closed', 2), ('checkpoint', 3), ('queued-input', 4), ('open-turn', 5), ('open-step', 6), ('unstarted-tools', 7), ('started-tool', 8)]:
        value = rows[name]['value']; assert value['inherited'] == cut+1
        assert value['events'][cut+1]['type'] == 'session/end-seed'
        assert value['parent'] is value['origin'] is None and value['workspace']
    started = rows['started-tool']['value']['events'][10:]
    assert [event['type'] for event in started] == ['tool/result', 'tool/result', 'step/end', 'turn/end']
    assert [event['data']['error']['code'] for event in started[:2]] == ['TOOL_OUTCOME_UNKNOWN', 'TOOL_NOT_STARTED']
    assert started[0]['sourceEventSeqs'] == [8] and 'sourceEventSeqs' not in started[1]
    assert started[-1]['data']['reason'] == dict(kind='forked')
    assert rows['cold-exact']['value'] == rows['started-tool']['value'] and rows['cold-exact']['sourceInactive']
    assert rows['parent-unmodified'] == dict(name='parent-unmodified', same=True, attachments=9)
    assert rows['continued-actual-agent']['turnEnd'] == 'completed'
    assert rows['migration-refused']['code'] == 'session/migration-required'
    migrated = rows['migration-permitted-passive']
    assert migrated['sourceUnchanged'] and migrated['sourceInactive'] and migrated['sourceStatus'] == 'migration-required'
    assert migrated['value']['inherited'] == 3


def test_core_fork_validates_identity_before_boundary_and_preserves_v4_inherited_cut():
    from dsh.core.session.current_session import CurrentSessionStore, CurrentSession
    store = CurrentSessionStore(None, 4); source = store.create('source')
    source.append('turn/start', dict(turn=1)); store.create('occupied')
    for subject, boundary, identity, code in [('missing', -1, 'occupied', 'SESSION_ALREADY_EXISTS'),
            ('missing', -1, 'new', 'SESSION_NOT_FOUND'),
            (CurrentSession('source', format_version=4), -1, 'new', 'SESSION_NOT_LIVE'),
            (source, -1, 'new', 'INVALID_BOUNDARY'), (source, 1, 'new', 'INVALID_BOUNDARY')]:
        with pytest.raises(Exception) as caught: store.fork(subject, boundary, identity)
        assert caught.value.code == code
    # Core Source fork permits numeric -0; the Remote branded boundary rejects it.
    child = store.fork(source, -0.0, 'child')
    assert child.inheritedEventCount == 1 and child.header.parentSession is None
    assert [event['type'] for event in child.snapshotEvents()] == ['turn/start','session/end-seed','turn/end']
    assert child.snapshotEvents()[-1]['time'] == source.snapshotEvents()[0]['time']


@pytest.mark.parametrize('tail', ['turn/start', 'agent/inbox/spliced', 'user/message'])
def test_omitted_boundary_excludes_queued_input_but_keeps_standalone_checkpoint(tail):
    events = [dict(type='turn/end', seq=0), dict(type='plugin:fixture/checkpoint', seq=1), dict(type=tail, seq=2, surfaceOp='append')]
    assert latest_completed_prefix_boundary(events) == 1
    events[-1]['surfaceOp'] = 'replace'
    assert latest_completed_prefix_boundary(events) == (2 if tail=='user/message' else 1)
    assert latest_completed_prefix_boundary([]) is None


@pytest.mark.parametrize('value', [-1, -0.0, True, .5, float('nan'), float('inf'), 9007199254740992, '1', None])
@pytest.mark.asyncio
async def test_invalid_sequence_rejected_before_source_observation(value):
    commands = AuthorizedSessionCommands(NS(get=lambda _: pytest.fail('invalid boundary read a provider')), NS())
    with pytest.raises(Exception) as caught: await commands.fork(dict(sessionId='s', atSeq=value))
    assert caught.value.code == 'gateway/bad-request'


@pytest.mark.parametrize('failure', ['boundary', 'workspace', 'composition', 'creation', 'attach'])
@pytest.mark.asyncio
async def test_fork_failures_release_observation_and_preserve_creation_boundary(failure):
    ctx = Context(); disposed = []; created = []; original = RuntimeError('composition failed')
    observation = NS(events=[dict(type='turn/end', seq=0, time=1, data=dict(turn=1,reason=dict(kind='completed')))],
        header=NS(id='s', cwd='/work', origin=None), dispose=lambda: disposed.append(True))
    async def observe(_): return observation
    async def composition(_):
        if failure=='composition': raise original
        return dict(setup=lambda *_: None)
    async def create(options):
        created.append(options)
        if failure=='creation': raise RuntimeError('create failed')
    async def attach(_): raise RuntimeError('attach failed')
    ctx.set_service('sessionQuery', NS(observeSession=observe))
    ctx.set_service('agents', NS(create=create)); ctx.set_service('agentDefaultModel', NS(currentSelection=lambda: dict(provider='p',model='m')))
    commands = AuthorizedSessionCommands(ctx, NS(composeAgent=composition, presetForObservation=lambda _: None))
    async def workspace(_):
        if failure=='workspace': raise RuntimeError('workspace failed')
        return NS(id='w',attachSession=attach) if failure=='attach' else None
    commands.fork_workspace = workspace
    try:
        with pytest.raises(Exception) as caught: await commands.fork(dict(sessionId='s', **(dict(atSeq=4) if failure=='boundary' else {})))
        assert disposed == [True]
        if failure=='composition': assert caught.value is original
        else: assert caught.value.code == ('session/fork-unavailable' if failure=='boundary' else 'session/workspace-attach-failed' if failure=='attach' else 'gateway/internal')
        assert bool(created) == (failure in ('creation','attach'))
        if failure=='attach':
            assert caught.value.details['sessionId'] == created[0]['sessionId']
            assert 'parentSession' not in created[0]['meta']
    finally: await ctx.fiber.dispose()


@pytest.mark.parametrize('resident,raced,allow', [(True,False,False),(False,True,False),(False,False,True),(False,False,None),(False,False,False)])
@pytest.mark.asyncio
async def test_preflight_rereads_residency_after_metadata_await(resident,raced,allow):
    ctx = Context(); attached = [resident]; gate, entered = asyncio.Event(), asyncio.Event(); calls = []
    ctx.set_service('sessions', NS(get=lambda _: NS() if attached[0] else None))
    async def stat(sid): entered.set(); await gate.wait(); calls.append(('stat',sid)); return dict(formatStatus='migration-required')
    async def fork(request): calls.append(('fork',request)); return dict(sessionId='child')
    ctx.set_service('sessionPersistence', NS(stat=stat)); facade = NS(ctx=ctx, commands=NS(fork=fork))
    request = dict(sessionId='s', **({} if allow is None else dict(allowMigration=allow)))
    pending = asyncio.ensure_future(AuthorizedSessionController.fork(facade,request))
    try:
        if allow is False and not resident:
            await entered.wait(); attached[0] = raced
        gate.set()
        if not resident and not raced and allow is False:
            with pytest.raises(Exception) as caught: await pending
            assert caught.value.code == 'session/migration-required' and calls == [('stat','s')]
        else:
            assert await pending == dict(sessionId='child') and calls[-1] == ('fork',request)
            assert len(calls) == (2 if raced else 1)
    finally:
        gate.set(); await asyncio.gather(pending,return_exceptions=True); await ctx.fiber.dispose()
