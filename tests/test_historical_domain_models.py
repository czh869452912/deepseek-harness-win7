"""Historical models retain provenance and cannot qualify current contracts."""
import copy
import importlib
import json

import pytest

from historical_domain_models import DOMAINS, ROOT, SUCCESSORS, historical_identity, historical_pair
from release_gate_fixtures import historical_source


@pytest.mark.parametrize('name', sorted(DOMAINS))
def test_historical_domain_guard_keeps_original_facts_and_rejects_changed_inputs(name):
    original = historical_source(name)
    source, native = historical_pair(name)
    module = importlib.import_module('scripts.' + name.replace('-', '_') + '_oracle')
    guard = historical_identity(name, module.identity)
    arguments = () if name in ('javascript-errors', 'canonical-llm', 'llm-metadata',
                               'llm-config', 'llm-prepared', 'deepseek-capture',
                               'deepseek-error', 'javascript-initial', 'javascript-ready',
                               'persistence-read', 'runtime-context', 'runtime-full-request',
                               'session-diagnostic', 'session-number', 'session-restore-sign') else (ROOT / 'reference',)
    guard(source, *arguments)
    altered = copy.deepcopy(source)
    altered['inputs'][next(iter(altered['inputs']))] = '0' * 64
    with pytest.raises(ValueError, match='guarded bytes'):
        guard(altered, *arguments)
    assert historical_source(name) == original
    key='rows' if 'rows' in original else 'observations'
    assert source[key] == original[key]
    assert source['sourceCommit'] == original['sourceCommit']
    assert source['node'] == original['node']
    plan = json.loads((ROOT / 'migration/candidates/rc022/release-gate-plan.json').read_text(encoding='utf-8'))
    current = {row['script'] for row in plan['paired']}
    assert all('scripts/' + successor + '_probe.py' in current for successor in SUCCESSORS[name])


def test_historical_domain_models_refuse_unreviewed_contract():
    with pytest.raises(ValueError, match='Unreviewed'):
        historical_pair('current-release')


@pytest.mark.parametrize('name', ['javascript-initial', 'javascript-ready'])
def test_worker_oracle_identity_checks_checkout_bytes_by_default(name, monkeypatch):
    source=historical_source(name)
    module=importlib.import_module('scripts.'+name.replace('-','_')+'_oracle')
    module.identity(source,check_files=False)
    monkeypatch.setattr(module,'digest',lambda path:'0'*64)
    with pytest.raises(ValueError,match='Source input bytes changed'):
        module.identity(source)


@pytest.mark.parametrize('name', ['http-redirect', 'tool-scheduler'])
def test_original_historical_rows_match_fresh_retained_provider_and_have_current_successors(name):
    from historical_domain_models import ROWS_SUCCESSORS, historical_rows_pair
    original = historical_source(name)
    native, expected = historical_rows_pair(name)
    validator = importlib.import_module('scripts.' + name.replace('-', '_') + '_oracle')
    assert native['rows'] == original
    assert validator.identity(original) == expected
    assert historical_source(name) == original
    plan = json.loads((ROOT / 'migration/candidates/rc022/release-gate-plan.json').read_text(encoding='utf-8'))
    scripts = {row['script'] for row in plan['paired']}
    assert all('scripts/' + successor + '_probe.py' in scripts for successor in ROWS_SUCCESSORS[name])


def test_historical_row_models_refuse_unreviewed_contract():
    from historical_domain_models import historical_rows_pair
    with pytest.raises(ValueError, match='Unreviewed'):
        historical_rows_pair('current-release')
