"""Approval audit-stream contracts over real Session, Loader, and publication."""

import gc
import weakref

import pytest

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader, LoaderUpdateError
from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.core.session import Session, SessionStore
from dsh.diagnostics.invariants import InvariantError, InvariantRegistry
from dsh.interaction.approval_invariant import ApprovalInvariantPlugin, PACKAGE_NAME
from dsh.interaction.user_approval import UserApprovalPlugin


async def environment(companion=True):
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(InvariantRegistry)
    if companion:
        await ctx.plugin(ApprovalInvariantPlugin)
    return ctx


def start(session):
    session.append('turn/start', {'turn': 1})


@pytest.mark.asyncio
async def test_accepts_pairs_policy_and_reuses_id_only_after_decision():
    ctx = await environment()
    try:
        session = ctx.get('sessions').create()
        start(session)
        for outcome in ('allowed-once', 'rejected', 'cancelled', 'unavailable'):
            session.append('approval/asked', dict(id='ask-1', toolName='pwsh'))
            session.append('approval/decided', dict(id='ask-1', outcome=outcome))
        session.append('approval/policy', {'policy': 'never'})
        session.append('turn/end', {'turn': 1, 'reason': {'kind': 'completed'}})
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_rebuilds_pending_request_from_existing_session():
    ctx = await environment(False)
    try:
        session = ctx.get('sessions').create()
        start(session)
        session.append('approval/asked', dict(id='resumed', toolName='pwsh'))
        await ctx.plugin(ApprovalInvariantPlugin)
        session.append('approval/decided', dict(id='resumed', outcome='cancelled'))
        session.append('turn/end', {'turn': 1, 'reason': {'kind': 'completed'}})
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_bare_publication_and_same_id_sessions_keep_separate_pairing():
    ctx = await environment()
    try:
        sessions = [Session('same-id'), Session('same-id')]
        for index, session in enumerate(sessions):
            ctx.emit('session/event', session, dict(type='turn/start', seq=0, time=0, data={'turn': 1}))
            ctx.emit('session/event', session, dict(type='approval/asked', seq=1, time=0, data=dict(id=str(index), toolName='pwsh')))
        with pytest.raises(InvariantError, match='no matching approval/asked'):
            ctx.emit('session/event', sessions[0], dict(type='approval/decided', seq=2, time=0, data=dict(id='1', outcome='rejected')))
        for index, session in enumerate(sessions):
            ctx.emit('session/event', session, dict(type='approval/decided', seq=2, time=0, data=dict(id=str(index), outcome='rejected')))
        reference = weakref.ref(session)
        del sessions, session
        gc.collect()
        assert reference() is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,data,message', [
    ('approval/asked', dict(id='ask', toolName='pwsh'), 'outside any open turn'),
    ('approval/decided', dict(id='ask', outcome='rejected'), 'outside any open turn'),
])
async def test_idle_audit_rejects_before_commit(kind, data, message):
    ctx = await environment()
    try:
        session = ctx.get('sessions').create()
        with pytest.raises(InvariantError, match=message):
            session.append(kind, data)
        assert session.events == []
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,data,message', [
    ('approval/asked', dict(id='fresh', toolName=''), 'toolName must be non-empty'),
    ('approval/asked', dict(id='open', toolName='pwsh'), 'repeated open id'),
    ('approval/decided', dict(id='missing', outcome='rejected'), 'no matching approval/asked'),
    ('approval/decided', dict(id='open', outcome='invalid'), 'unknown outcome'),
    ('approval/policy', dict(policy='sometimes'), 'unknown policy'),
])
async def test_invalid_candidate_preserves_committed_pending_question(kind, data, message):
    ctx = await environment()
    try:
        session = ctx.get('sessions').create()
        start(session)
        session.append('approval/asked', dict(id='open', toolName='pwsh'))
        before = list(session.events)
        with pytest.raises(InvariantError, match=message):
            session.append(kind, data)
        assert session.events == before
        session.append('approval/decided', dict(id='open', outcome='rejected'))
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_loader_mount_unload_and_invalid_replay_roll_back_registration():
    ctx = await environment(False)
    try:
        loader = Loader(ctx)
        install_harness_plugin_classes(loader)
        await loader.root.update([dict(id='approval-invariant', name=PACKAGE_NAME + '/invariant')])
        assert ctx.get('invariants').registrations == {PACKAGE_NAME}
        session = ctx.get('sessions').create()
        start(session)
        session.append('approval/asked', dict(id='open', toolName='pwsh'))
        await loader.root.update([])
        assert ctx.get('invariants').registrations == set()
        session.append('approval/decided', dict(id='open', outcome='cancelled'))
        session.append('turn/end', {'turn': 1, 'reason': {'kind': 'completed'}})
        session.append('approval/asked', dict(id='unenclosed', toolName='pwsh'))
        with pytest.raises(LoaderUpdateError, match='outside any open turn'):
            await loader.root.update([dict(id='approval-invariant', name=PACKAGE_NAME + '/invariant')])
        assert PACKAGE_NAME not in ctx.get('invariants').registrations
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_later_precommit_veto_does_not_reserve_rejected_id():
    ctx = await environment()
    try:
        session = ctx.get('sessions').create()
        start(session)
        candidates = []

        def veto(_mode, name, args, *extra):
            if name == 'session/event' and args[1]['type'] == 'approval/asked':
                candidates.append(weakref.ref(args[1]))
                raise ValueError('later precommit veto')

        remove = ctx.on('internal/dispatch', veto, global_listener=True)
        for _ in range(3):
            with pytest.raises(ValueError, match='later precommit veto'):
                session.append('approval/asked', dict(id='vetoed', toolName='pwsh'))
        remove()
        session.append('approval/asked', dict(id='vetoed', toolName='pwsh'))
        session.append('approval/decided', dict(id='vetoed', outcome='cancelled'))
        gc.collect()
        assert all(candidate() is None for candidate in candidates)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_service_cancellation_has_valid_pair_in_original_order():
    from dsh.core.abort import AbortSignal
    ctx = await environment()
    try:
        await ctx.plugin(UserApprovalPlugin)
        session = ctx.get('sessions').create()
        start(session)
        class AgentView:
            pass
        agent = AgentView()
        agent.session = session
        assert await ctx.get('approval').request(dict(agent=agent, toolName='pwsh', signal=AbortSignal.abort())) == 'cancelled'
        assert [entry['type'] for entry in session.events] == ['turn/start', 'approval/asked', 'approval/decided']
    finally:
        await ctx.fiber.dispose()
