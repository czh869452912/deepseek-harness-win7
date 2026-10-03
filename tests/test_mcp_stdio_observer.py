import copy

import pytest

from scripts.mcp_stdio_oracle import MODES, classify, expected_row, validate_observations


def observations():
    return [expected_row(mode) for mode in MODES]


def test_source_and_native_must_preserve_all_twenty_actual_process_observations():
    source = observations()
    assert len(classify(source, copy.deepcopy(source))) == 20


@pytest.mark.parametrize('mode', ['cap-logging-array', 'cap-experimental-false', 'tool-annotations-false',
    'tool-properties-array', 'tool-unknown', 'id-decimal', 'id-hex', 'id-empty', 'malformed-then-valid'])
def test_schema_projection_and_sdk_correlation_cannot_be_normalized(mode):
    rows = observations()
    row = rows[MODES.index(mode)]
    if mode == 'malformed-then-valid':
        row['protocolErrors'][0]['message'] = 'ignored malformed envelope'
    elif 'error' in row:
        row['error']['message'] = 'normalized rejection'
    elif mode.startswith('id-'):
        row['frames'][1]['packet']['id'] = 0
    else:
        row['tools'] = {'tools': []}
    with pytest.raises(ValueError):
        classify(observations(), rows)


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'closed', 'reaped', 'frames', 'extra'])
def test_mcp_missing_corrupt_or_fabricated_fields_cannot_pass(mode, damage):
    rows = observations()
    index = MODES.index(mode)
    if damage == 'missing':
        rows.pop(index)
    elif damage == 'duplicate':
        rows[index]['mode'] = 'duplicate'
    elif damage == 'closed':
        rows[index]['closed'] = False
    elif damage == 'reaped':
        rows[index]['reaped'] = False
    elif damage == 'frames':
        rows[index]['frames'].append({'direction': 'received', 'packet': {'method': 'fabricated'}})
    else:
        rows[index]['ignored-extra-result'] = True
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('mode', ['peer-error', 'peer-error-null', 'cancel', 'timeout', 'eof'])
def test_error_data_cancellation_reason_and_late_result_are_not_normalized(mode):
    rows = observations()
    rows[MODES.index(mode)]['error'] = {'message': 'success'}
    with pytest.raises(ValueError):
        classify(observations(), rows)
