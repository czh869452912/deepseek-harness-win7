"""Original callback observations plus native language boundary verification."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from dsh.extensions.cordis_prompt import native_contracts, SOURCE_CONTRACTS

ROOT = Path(__file__).resolve().parents[1]
SPECS = json.loads((ROOT / 'scripts/oracles/cordis-tools-cases.json').read_text(encoding='utf-8'))
FIXTURE = json.loads((ROOT / 'tests/fixtures/cordis-tools-source-observations.json').read_text(encoding='utf-8'))
spec = importlib.util.spec_from_file_location('cordis_tools_probe', ROOT / 'scripts/oracles/cordis_tools_python.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.asyncio
@pytest.mark.parametrize('index', range(len(SPECS)), ids=[row['mode'] for row in SPECS])
async def test_actual_native_registration_against_original_callback(index):
    case = SPECS[index]
    try:
        actual = dict(mode=case['mode'], value=await probe.observe(case))
    except Exception as error:
        actual = dict(mode=case['mode'], error=dict(message=getattr(error, 'message', str(error))))
    assert actual == FIXTURE['observations'][index]


def test_original_evidence_inputs_remain_pinned():
    assert FIXTURE['target_upstream'] == SOURCE_CONTRACTS['target_upstream']
    assert len(SPECS) == len(FIXTURE['observations'])
    for path, digest in FIXTURE['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


def test_native_host_guidance_and_parameter_contract_are_explicit():
    contracts = native_contracts()
    assert contracts['order'] == 2500
    assert 'Python 3.8.10 source that declares a callable named plugin' in contracts['prompt']
    assert 'plugin.inject' in contracts['prompt']
    assert 'plain JavaScript function body' in contracts['prompt']
    assert 'DSH Node.js process' not in contracts['prompt']
    assert 'load the cordis-plugin-development Skill' not in contracts['prompt']
    original = {row['name']: row for row in SOURCE_CONTRACTS['definitions']}
    for row in contracts['definitions']:
        assert row['outputSchema'] == original[row['name']]['outputSchema']
        if row['name'] != 'cordis_define':
            assert row == original[row['name']]
    contracts['definitions'][0]['parameters']['additionalProperties'] = 'mutated'
    assert native_contracts()['definitions'][0]['parameters'] == original['cordis_inspect_list']['parameters']
