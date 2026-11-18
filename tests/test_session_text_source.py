import copy
from pathlib import Path

import pytest
from scripts import session_text_oracle
from historical_locale_models import locale_pair


@pytest.fixture(scope='module')
def paired(tmp_path_factory):
    output = tmp_path_factory.mktemp('session-text-paired') / 'result.json'
    return locale_pair('session-text', output)


def test_historical_original_and_retained_native_text_extraction_and_domain_order(paired):
    report, source, native = paired
    assert report['status'] == 'passed' and report['cases'] == 7883
    expected_digest, expected_locale = session_text_oracle.source_identity(source)
    session_text_oracle.validate_runtime(native, session_text_oracle.ROOT, expected_digest, expected_locale)


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'runtime', 'data', 'locale', 'normalization',
                                   'comparison', 'extraction', 'order', 'digest', 'inventory'])
def test_damaged_text_observations_and_runtime_identity_are_refused(paired, damage):
    _, source, original = paired
    native = copy.deepcopy(original)
    expected_digest, expected_locale = session_text_oracle.source_identity(source)
    if damage == 'missing':
        native = None
    elif damage == 'root':
        native['root'] = str(Path(native['root']) / 'foreign')
    elif damage == 'module':
        native['moduleFile'] = 'foreign'
    elif damage == 'runtime':
        native['python'] = '3.9.0'
    elif damage == 'data':
        native['unicodeDataSha256'] = '0' * 64
    elif damage == 'locale':
        native['runtime']['locale'] = 'foreign'
    elif damage == 'normalization':
        native['runtime']['normalization'] = 16
    elif damage == 'comparison':
        native['observations']['cases'][0]['matched'] = False
    elif damage == 'extraction':
        native['observations']['events'][0] = 'foreign'
    elif damage == 'order':
        native['observations']['orders'][0]['listed'].reverse()
    elif damage == 'digest':
        expected_digest = '0' * 64
    else:
        native['observations']['cases'].pop()
    with pytest.raises(ValueError):
        session_text_oracle.validate_runtime(native, session_text_oracle.ROOT, expected_digest, expected_locale)
