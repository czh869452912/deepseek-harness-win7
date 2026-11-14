"""Current full captures retain system-message and catalog identity constraints."""
import copy
from pathlib import Path
from evidence_fixtures import read_member

import pytest

from scripts import engine_composition_oracle, route_execution_oracle


ARCHIVE = Path(__file__).resolve().parents[1] / 'migration/evidence/artifacts/RC3-ENGINE-ROUTE-TARGETED-20261017.zip'


@pytest.fixture(scope='module', params=['engine', 'route'])
def current_pair(request):
    folder = 'rc3-%s-current-diagnostic-20261017-a/' % request.param
    source, native = [read_member(ARCHIVE.name, folder + name + '.json') for name in ('source', 'native')]
    oracle = engine_composition_oracle if request.param == 'engine' else route_execution_oracle
    return oracle, source, native


def test_actual_current_full_capture_matches(current_pair):
    oracle, source, native = current_pair
    assert oracle.compare(source, native)['status'] == 'matched'


@pytest.mark.parametrize('damage', ['system-text', 'system-identity', 'tool-schema', 'unknown-child'])
def test_current_capture_rejects_prompt_schema_and_identity_drift(current_pair, damage):
    oracle, source, original = current_pair
    native = copy.deepcopy(original)
    public = native['rows'][0]['public']
    if damage == 'tool-schema':
        tool = next(tool for tool in public['requests'][0]['request']['tools'] if tool['name'] == 'present')
        tool['parameters']['properties']['files']['items']['properties']['path']['description'] += ' changed'
    elif damage == 'unknown-child':
        event = next(item['event'] for item in public['events'] if item['event']['type'] == 'subagent/catalog')
        event['data']['childId'] = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
    else:
        event = next(item['event'] for item in public['events'] if item['event']['type'] == 'system/message')
        message = event['data']['message']
        if damage == 'system-text':
            message['content'][0]['text'] += '\nChanged system instructions'
        else:
            message['id'] = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
    assert oracle.compare(source, native)['status'] == 'different'
