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
    arguments = () if name == 'javascript-errors' else (ROOT / 'reference',)
    guard(source, *arguments)
    altered = copy.deepcopy(source)
    altered['inputs'][next(iter(altered['inputs']))] = '0' * 64
    with pytest.raises(ValueError, match='guarded bytes'):
        guard(altered, *arguments)
    assert historical_source(name) == original
    assert source['rows'] == original['rows']
    assert source['sourceCommit'] == original['sourceCommit']
    assert source['node'] == original['node']
    plan = json.loads((ROOT / 'migration/candidates/rc022/release-gate-plan.json').read_text(encoding='utf-8'))
    current = {row['script'] for row in plan['paired']}
    assert all('scripts/' + successor + '_probe.py' in current for successor in SUCCESSORS[name])


def test_historical_domain_models_refuse_unreviewed_contract():
    with pytest.raises(ValueError, match='Unreviewed'):
        historical_pair('current-release')
