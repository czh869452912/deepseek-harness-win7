"""Historical prerequisite reads never require the installed Session vocabulary."""
import pytest

from dsh.session.format import SessionFormatError
from dsh.session.format_catalog import historicalSessionFormatCatalog as catalog
from dsh.session.format_v0_to_v1.payload import compact


@pytest.mark.parametrize('version', [0, 1, 2, 3])
def test_historical_child_header_and_empty_seed(version):
    header = dict(type='session', version=version, id='child', createdAt=1,
                  parentSession='parent', origin='subagent', delegationDepth=1, agentPreset='worker')
    if version < 2:
        header['seedLength'] = 0
    else:
        header['isSeeded'] = True
    restore = catalog.createRestore(header, dict(validation='historical', recovery='strict'))
    marker = dict(type='session/end-seed', seq=0, time=1, data={'inherited': True})
    if version >= 2:
        restore.decodeRow(marker)
    artifact = restore.finish()
    assert artifact['header']['version'] == 3
    assert artifact['header']['parentSession'] == 'parent'
    assert artifact['inheritedEventCount'] == 0
    assert artifact['events'] == [marker]
    if version < 2:
        assert compact(artifact['header']) == ('{"version":3,"id":"child","createdAt":1,"parentSession":"parent",'
            '"isSeeded":true,"origin":"subagent","delegationDepth":1,"agentPreset":"worker"}')


def test_current_historical_read_preserves_future_opaque_rows():
    header = dict(type='session', version=3, id='child', createdAt=1, isSeeded=False,
                  delegationDepth=1)
    row = dict(type='future/opaque', seq=0, time=1, data={'unknown': True})
    restore = catalog.createRestore(header, dict(validation='historical', recovery='strict'))
    restore.decodeRow(row)
    assert restore.finish()['events'] == [row]
    restore = catalog.createRestore(header, dict(validation='current', recovery='strict'))
    restore.decodeRow(row)
    with pytest.raises(SessionFormatError):
        restore.finish()


def test_malformed_header_has_source_result_order():
    value = catalog.readHeader(dict(type='session', version=0, isSeeded=False))
    assert list(value) == ['status', 'storedVersion', 'targetVersion', 'reason']
    assert value['status'] == 'malformed'


def test_historical_catalog_refuses_native_v4():
    value = catalog.readHeader(dict(version=4))
    assert value['status'] == 'unsupported'
    assert value['targetVersion'] == 3
