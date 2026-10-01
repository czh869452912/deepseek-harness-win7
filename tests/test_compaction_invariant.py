"""Compaction relational contracts, shared with the pinned-source observer."""
import gc
import json
from pathlib import Path
import weakref

import pytest

from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.compaction.invariant import CompactionInvariantPlugin, PACKAGE_NAME
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader, LoaderUpdateError
from dsh.core.scope import create_scope, ScopeKey
from dsh.core.session import Session, SessionPlugin
from dsh.diagnostics.invariants import InvariantError, InvariantRegistry
from scripts.oracles.compaction_python import invariant

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'scripts/oracles/compaction-invariant-cases.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=[case['mode'] for case in CASES])
async def test_compaction_relations_and_precommit_atomicity(case):
    result = await invariant(case)
    expected_install = case.get('expectedInstallError')
    if expected_install:
        assert result['installation'] == dict(
            error='invariant violated by "{}": {}'.format(PACKAGE_NAME, expected_install), code='INVARIANT')
        assert result['receipts'] == []
        return
    assert result['installation'] is None
    assert len(result['receipts']) == len(case['actions'])
    for action, receipt in zip(case['actions'], result['receipts']):
        if 'expectedError' in action:
            detail = action['expectedError']
            assert receipt['accepted'] is False
            assert receipt['unchanged'] is True
            assert receipt['error'] == (detail if action.get('veto') else
                'invariant violated by "{}": {}'.format(PACKAGE_NAME, detail))
            assert receipt['code'] == (None if action.get('veto') else 'INVARIANT')
        else:
            assert receipt['accepted'] is True, receipt
    assert [event['seq'] for event in result['events']] == list(range(len(result['events'])))


async def environment():
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(InvariantRegistry)
    return ctx


@pytest.mark.asyncio
async def test_loader_resolves_all_four_real_companions_and_reverses_ownership(tmp_path):
    ctx = await environment()
    ctx.baseUrl = str(tmp_path)
    try:
        await ctx.plugin(Loader)
        loader = ctx.get('loader')
        install_harness_plugin_classes(loader)
        packages = [PACKAGE_NAME, '@deepseek-ai/dsh-compaction-basic',
            '@deepseek-ai/dsh-command-compact', '@deepseek-ai/dsh-compaction-tool-result-pruner']
        await loader.root.update([dict(id=str(index), name=package + '/invariant')
            for index, package in enumerate(packages)])
        assert ctx.get('invariants').registrations == set(packages)
        session = ctx.get('sessions').create()
        with pytest.raises(InvariantError, match='no matching compaction/start'):
            session.append('compaction/end', dict(compactionId='fixture', turn=None, error='failed'))
        await loader.root.update([])
        assert ctx.get('invariants').registrations == set()
        session.append('compaction/end', dict(compactionId='fixture', turn=None, error='failed'))
        # Replay rejects the malformed log rather than silently activating.
        with pytest.raises(LoaderUpdateError, match='no matching compaction/start'):
            await loader.root.update([dict(id='main', name=PACKAGE_NAME + '/invariant')])
        assert PACKAGE_NAME not in ctx.get('invariants').registrations
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_companion_global_ownership_disposal_reload_and_same_id_sessions():
    ctx = await environment()
    try:
        scope = create_scope(ctx, ScopeKey(object()))
        companion = await scope.ctx.plugin(CompactionInvariantPlugin)
        session = ctx.get('sessions').create()
        session.append('compaction/start', dict(compactionId='first', turn=None))
        other = Session(session.id)
        # Session objects sharing the same durable id keep independent traces.
        ctx.emit('session/event', other, dict(type='compaction/start', seq=0, time=0,
            data=dict(compactionId='other', turn=None)))
        ctx.emit('session/event', other, dict(type='compaction/end', seq=1, time=0,
            data=dict(compactionId='other', turn=None, error='failed')))
        with pytest.raises(InvariantError, match='still compacting'):
            session.append('compaction/start', dict(compactionId='second', turn=None))
        await companion.dispose()
        assert PACKAGE_NAME not in ctx.get('invariants').registrations
        session.append('compaction/end', dict(compactionId='first', turn=None, error='failed'))
        reloaded = await ctx.plugin(CompactionInvariantPlugin)
        session.append('compaction/start', dict(compactionId='second', turn=None))
        session.append('compaction/end', dict(compactionId='second', turn=None, error='failed'))
        await reloaded.dispose()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_rejected_candidates_and_bare_sessions_are_not_retained():
    ctx = await environment()
    try:
        await ctx.plugin(CompactionInvariantPlugin)
        session = ctx.get('sessions').create()
        candidates = []
        def veto(_mode, name, args, *extra):
            if name == 'session/event':
                candidates.append(weakref.ref(args[1]))
                raise ValueError('reject candidate')
        remove = ctx.on('internal/dispatch', veto, global_listener=True)
        for _ in range(20):
            try:
                session.append('compaction/start', dict(compactionId='rejected', turn=None))
            except ValueError:
                pass
        remove()
        gc.collect()
        # SurfaceManager keeps one prepared validation candidate. Earlier
        # rejected candidates must be collectible, and the next commit clears
        # the final prepared candidate as well.
        assert all(candidate() is None for candidate in candidates[:-1])
        assert session.events == []
        session.append('compaction/start', dict(compactionId='committed', turn=None))
        session.append('compaction/end', dict(compactionId='committed', turn=None, error='failed'))
        gc.collect()
        assert all(candidate() is None for candidate in candidates)
        bare = Session('ephemeral')
        ctx.emit('session/event', bare, dict(type='compaction/start', seq=0, time=0,
            data=dict(compactionId='bare', turn=None)))
        reference = weakref.ref(bare)
        del bare
        gc.collect()
        assert reference() is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_installer_waits_for_sessions_and_removes_registration_when_disposed():
    ctx = Context()
    try:
        await ctx.plugin(InvariantRegistry)
        fiber = ctx.plugin(CompactionInvariantPlugin)
        await ctx.fiber.await_settled()
        await ctx.plugin(SessionPlugin)
        await fiber
        session = ctx.get('sessions').create()
        with pytest.raises(InvariantError, match='no matching compaction/start'):
            session.append('compaction/end', dict(compactionId='fixture', turn=None, error='failed'))
        await fiber.dispose()
        assert PACKAGE_NAME not in ctx.get('invariants').registrations
    finally:
        await ctx.fiber.dispose()
