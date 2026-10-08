import copy
import json
from pathlib import Path
import zipfile

import pytest

from scripts.route_execution_oracle import compare, digest


@pytest.fixture(scope='module')
def historical_route_values():
    archive = Path(__file__).resolve().parents[1] / 'migration/evidence/artifacts/ROUTE-PATH-BROWSER-RESEARCH-20261007-6AABEA10.zip'
    assert digest(archive) == 'a6d37689e5b2f51c4e89cc543dadf14d4cce7c77b8b8bd142dae1d7baf0694c8'
    with zipfile.ZipFile(str(archive)) as package:
        source = json.loads(package.read('route-execution-source-v10.json'))
    native = copy.deepcopy(source)
    native['root'] = source['sourceRoot'] + '\\'
    return source, native


def test_complete_route_values_keep_valid_baseline(historical_route_values):
    assert compare(*historical_route_values)['status'] == 'matched'


@pytest.mark.parametrize('damage', ('request-model', 'request-system', 'request-tool-order',
                                   'event-order', 'unknown-id', 'missing-value'))
def test_route_values_refuse_business_changes(historical_route_values, damage):
    source, native = historical_route_values
    native = copy.deepcopy(native)
    row = native['rows'][0]
    request = row['public']['requests'][0]['request']
    if damage == 'request-model':
        request['model'] = 'wrong-child-model'
    elif damage == 'request-system':
        request['system'] += '\nExtra instructions'
    elif damage == 'request-tool-order':
        request['tools'].reverse()
    elif damage == 'event-order':
        row['public']['events'].reverse()
    elif damage == 'unknown-id':
        request['unclassifiedIdentity'] = 'literal-unknown-value'
    else:
        del request['reasoningEffort']
    assert compare(source, native)['status'] == 'different'


def test_route_values_refuse_unsupported_installation_projection(historical_route_values):
    source, native = historical_route_values
    native = copy.deepcopy(native)
    native['root'] = 'an unverified installation'
    with pytest.raises(AssertionError):
        compare(source, native)
