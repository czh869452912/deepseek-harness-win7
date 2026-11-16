import asyncio

import pytest

from dsh.boot.plugin_manager_current import diagnostic_version, management_error, ManagementFailure
from dsh.cordis.errors import ThrownValueError
from scripts.rc022_plugin_manager_core_probe import observe


@pytest.mark.asyncio
async def test_actual_profile_manager_live_startup_overrides_and_operation_facts(tmp_path):
    rows = {row['name']: row for row in await asyncio.wait_for(observe(tmp_path), 60)}
    assert len(rows) == 9
    assert all(row['lockReleased'] for row in rows.values())
    live = rows['live']['steps']
    assert live[0]['result'] == dict(stage='enable', target='include:managed', enabled=False,
                                     changed=True, application='applied', warnings=[])
    assert live[0]['managed']['enabled'] is False
    assert not live[1]['result']['changed']
    assert live[2]['managed']['enabled'] is True
    assert live[3]['result']['error'] == dict(code='management-required')
    assert live[4]['result']['error'] == dict(code='unknown-plugin')
    assert rows['foreign']['steps'][-1]['result']['error'] == dict(code='unaddressable')
    assert rows['startup']['steps'][0]['result']['application'] == 'restart-required'
    assert rows['startup']['steps'][0]['managed']['enabled'] is True
    assert rows['overlay']['steps'][2]['result']['application'] == 'overridden'
    assert rows['pending']['steps'][0]['result']['application'] == 'overridden'
    assert rows['pending']['steps'][2]['result']['restartReason'] == 'host-module'
    assert rows['reload-error']['steps'][0]['result']['changed'] is True
    assert rows['reload-error']['steps'][0]['result']['error'] == dict(code='operation-error', diagnostic='reload failed')
    for mode in ('lock-error', 'unloaded'):
        assert all(step['result'] == dict(threw=True) for step in rows[mode]['steps'])
        assert rows[mode]['changed'] == []
    assert [event['phase'] for event in rows['lock-error']['facts']] == ['started', 'unknown'] * 5
    assert rows['unloaded']['facts'] == []  # Disposed owner cannot dispatch diagnostics.
    assert rows['diagnostic-failure']['steps'][0]['result']['application'] == 'applied'
    assert all(event['validTime'] for row in rows.values() for event in row['facts'])
    for row in rows.values():
        assert all(event['target'] is None for event in row['facts'] if event['operation'] == 4)


def test_management_error_keeps_expected_codes_and_bounds_diagnostic_versions():
    assert management_error(ManagementFailure('unknown-plugin')) == dict(code='unknown-plugin')
    assert management_error(ManagementFailure('incompatible-version', [dict(name='plugin')])) == dict(code='incompatible-version', incompatible=[dict(name='plugin')])
    assert management_error(ThrownValueError(dict(reason='raw'))) == dict(code='operation-error', diagnostic='[object Object]')
    assert diagnostic_version('x' * 128) == 'x' * 128
    assert diagnostic_version('x' * 129) is None
    assert diagnostic_version('\U0001f431' * 65) is None
