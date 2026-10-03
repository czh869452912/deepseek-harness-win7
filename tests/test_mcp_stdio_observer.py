import copy

import pytest

from scripts.mcp_stdio_oracle import MODES, classify, expected_row, validate_observations


def observations():
    return [expected_row(mode) for mode in MODES]


def test_source_and_native_must_preserve_all_eleven_actual_process_observations():
    source = observations()
    assert len(classify(source, copy.deepcopy(source))) == 11


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
