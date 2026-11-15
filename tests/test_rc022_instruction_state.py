from types import SimpleNamespace as NS
from weakref import WeakKeyDictionary

import pytest

from dsh.context.agent_instructions import state_authorized as state, config_authorized as config
from dsh.core.abort import AbortController


@pytest.mark.asyncio
async def test_actual_session_reconciles_duplicates_promotions_and_group_rollback(tmp_path):
    from scripts.rc022_instruction_state_probe import observe
    rows={row['name']:row for row in await observe(tmp_path)}
    assert rows['initial']['reads'] == 5
    # Only a hidden duplicate is cached immediately; visible transitions are deferred.
    assert set(rows['initial']['cache']) == {'agents-global\0AGENTS.md'}
    assert rows['warm']['result'] is None and rows['warm']['reads'] == 0
    assert rows['hidden-duplicate-fast-path']['result'] is None and rows['hidden-duplicate-fast-path']['reads'] == 0
    promoted=rows['promote-hidden-sibling']['result']['context']['source']['changes']
    assert [(item['action'],item['scope']) for item in promoted] == [('remove','.\0AGENTS.md'),('set','.\0CLAUDE.md')]
    oversized=rows['oversized-group-rollback']['result']['context']['source']['changes']
    assert all(item['scope'].startswith(('user-global\0','agents-global\0')) for item in oversized)
    assert rows['unavailable-group-rollback']['result'] is None
    assert rows['notice-only-budget']['result'] is None
    assert rows['retry-after-budget']['result']['context']['source']['changes']
    baseline=rows['baseline-state']['value']
    assert set(baseline['changes']) == {'.\0AGENTS.md','pkg\0AGENTS.md'}
    assert set(baseline['versions']) == {'pkg\0AGENTS.md'}


def test_authority_validation_and_exact_retained_updates():
    source=dict(kind='agent-instructions',changes=[None,[],dict(action='unknown',scope='x',path='x'),
        dict(action='set',scope=3,path='x'),dict(action='set',scope='x',path='x',digest=None),
        dict(action='remove',scope='valid',path='ok',extra='discard')])
    assert state.instruction_changes(source) == [dict(action='remove',scope='valid',path='ok')]
    change=dict(action='set',scope='x',path='x',digest='digest');update=dict(change=change,state=dict(version='one'))
    for key in ('action','scope','path','digest'):
        assert state.retained_instruction_version_updates([update],[dict(change,**{key:'other'})]) == []
    assert state.retained_instruction_version_updates([update],[dict(change,ignored=True)]) == [update]


def test_cache_updates_are_session_isolated_and_remove_empty_owner():
    class Session:pass
    one,two=Session(),Session();cache=WeakKeyDictionary();change=dict(action='set',scope='x',path='x')
    state.apply_instruction_version_updates(one,[],cache)
    assert one not in cache
    state.apply_instruction_version_updates(one,[dict(change=change,state=dict(version='one'))],cache)
    state.apply_instruction_version_updates(two,[dict(change=change,state=dict(version='two'))],cache)
    state.apply_instruction_version_updates(one,[dict(change=dict(change,action='remove'))],cache)
    assert one not in cache and cache[two]['x']['version'] == 'two'


@pytest.mark.asyncio
async def test_probe_cancellation_preserves_identity_and_does_not_publish_transition(tmp_path):
    class Session:
        surface=NS(nodes=[])
    session=Session();agent=NS(session=session);cache=WeakKeyDictionary();controller=AbortController();failure=RuntimeError('cancel metadata')
    async def resolve(path,opts):controller.abort(failure);raise RuntimeError('provider wrapper')
    filesystem=NS(resolve=resolve)
    resolved=dict(config.resolve_config(dict(maxBytes=65536)),dshHome=str(tmp_path/'home'),agentsHome=str(tmp_path/'shared'))
    with pytest.raises(RuntimeError) as caught:
        await state.reconcile_instruction_context(agent,resolved,cache,filesystem,dict(cwd=str(tmp_path),projectRoot=str(tmp_path),
            authorityMessages=[],scopeMessages=[],touchedPaths=[],includeBaselineScopes=True,signal=controller.signal))
    assert caught.value is failure and cache[session] == {}
