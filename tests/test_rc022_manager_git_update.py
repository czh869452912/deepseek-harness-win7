import asyncio

import pytest

from scripts.rc022_manager_git_update_probe import observe


@pytest.mark.asyncio
async def test_real_git_checks_gate_and_restore_without_disabling_old_version(tmp_path):
    rows={row['name']:row for row in await asyncio.wait_for(observe(tmp_path),60)}
    assert len(rows)==9 and all(row['remote'] for row in rows.values())
    for mode in ('git-live','git-permission','git-no-command'):
        row=rows[mode]
        assert row['result']['result']['application']=='applied' and row['probe']=='2.0.0'
        assert row['dependencies']['fresh'].endswith(row['commands'][-1][1].split('#')[-1])
        assert '--save-exact' not in row['commands'][-1]
    assert rows['git-disabled']['probe'] is None and rows['git-disabled']['selection']==['core']
    for mode in ('git-target-fails','git-activation-error','git-cancel'):
        row=rows[mode]
        assert row['result']['result']['application'] in ('failed','cancelled')
        assert row['result']['restore']['application']=='applied' and row['probe']=='1.0.0'
        assert row['updates'][-1]['step']=='restoring'
        assert any('requestId' not in event for event in row['logs'])
        assert '--save-exact' not in row['commands'][-1]
    assert rows['git-cancel']['cancel']==dict(status='cancelled')
    assert rows['git-restore-fails']['result']['restore']['application']=='failed'
    network=rows['git-network']
    assert network['result']['step']=='check' and network['result']['result']['failedAt']=='spec-host'
    package=network['result']['result']['packageResult']
    assert package['kind']=='network' and package['output'] and 'argv' not in package
    assert network['probe']=='1.0.0' and network['lock']=='original\r\n' and network['commands']==[]
    assert [event['step'] for event in network['updates']]==['checking']
    assert not network['facts'] and not network['changed']
