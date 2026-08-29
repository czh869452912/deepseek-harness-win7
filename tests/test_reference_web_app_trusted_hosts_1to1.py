import pytest
from dsh.cordis.profile import resolve_lan_trust


def test_resolve_lan_trust_loopback():
    res = resolve_lan_trust('127.0.0.1', [])
    assert res['lan_addresses'] == []
    assert res['trusted_hosts'] == []

    res_with_extra = resolve_lan_trust('127.0.0.1', ['lab.internal'])
    assert res_with_extra['lan_addresses'] == []
    assert res_with_extra['trusted_hosts'] == ['lab.internal']


def test_resolve_lan_trust_all_interfaces():
    res = resolve_lan_trust('0.0.0.0', ['harness.internal:3080'])
    assert 'harness.internal:3080' in res['trusted_hosts']
    for ip in res['lan_addresses']:
        assert not ip.startswith('127.')
        assert ip in res['trusted_hosts']
