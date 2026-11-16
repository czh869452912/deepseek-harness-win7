import asyncio

import pytest

from scripts.rc022_manager_update_probe import observe


@pytest.mark.asyncio
async def test_actual_update_preflight_expected_install_activation_and_restoration(tmp_path):
    rows={row['name']:row for row in await asyncio.wait_for(observe(tmp_path),90)}
    assert len(rows)==24 and all(row['remote'] for row in rows.values())
    live=rows['live']
    assert live['result']['result']['application']=='applied' and live['probe']=='2.0.0'
    assert live['dependencies']=={'fresh':'2.0.0'}
    assert [row['step'] for row in live['updates']]==['checking','removing','installing']
    mutations=[args for args in live['commands'] if args[0] in ('remove','add')]
    assert mutations==[['remove','fresh'],['add','fresh@2.0.0','--save-exact']]
    startup=rows['startup']
    assert startup['probe']=='1.0.0' and startup['dependencies']=={'fresh':'2.0.0'}
    assert startup['result']['result']['application']=='restart-required'
    assert all(args[0]!='remove' for args in startup['commands'])
    assert rows['disabled']['probe'] is None and rows['disabled']['selection']==['core']
    for mode in ('target-fails','activation-error','wrong-version','wrong-name','extra-dependency','plain-installed','incompatible-installed','cancel'):
        row=rows[mode]
        assert row['result']['result']['application'] in ('failed','cancelled')
        assert row['result']['restore']['application']=='applied'
        assert row['dependencies']=={'fresh':'1.0.0'} and row['probe']=='1.0.0'
        assert row['updates'][-1]['step']=='restoring'
        # Restoration has no request identity and cannot be cancelled by the failed target's id.
        assert any('requestId' not in event for event in row['logs'])
    assert rows['restore-fails']['result']['restore']['application']=='failed'
    assert rows['restore-fails']['dependencies']=={} and rows['restore-fails']['probe'] is None
    assert rows['activation-error']['result']['result']['stage']=='enable'
    assert len([args for args in rows['activation-error']['commands'] if args[0]=='remove'])==2
    assert rows['cancel']['cancel']=={'status':'cancelled'}
    assert rows['cancel']['result']['result']['application']=='cancelled'
    assert rows['removal-fails']['result']['step']=='remove'
    assert rows['removal-fails']['probe'] is None
    assert all(args[0]!='add' for args in rows['removal-fails']['commands'])
    for mode in ('preflight-plain','preflight-incompatible','bad-engines','lookup-failure','invalid-version','same-version','unknown','registry-spec','git-missing','git-branch','git-other'):
        row=rows[mode]
        assert row['result']['step']=='check' and row['result']['result']['application']=='failed'
        assert row['probe']=='1.0.0' and row['lock']=='original\r\n'
        assert all(args[0] not in ('remove','add') for args in row['commands'])
    assert rows['wrong-version']['result']['result']['error']['code']=='unexpected-package'
    assert rows['wrong-name']['result']['result']['error']['code']=='unexpected-package'
    assert rows['plain-installed']['result']['result']['error']['code']=='not-bundle'
    assert rows['incompatible-installed']['result']['result']['error']['code']=='incompatible-version'


@pytest.mark.asyncio
async def test_update_settles_lock_or_disposal_rejection_as_its_actual_step(monkeypatch,tmp_path):
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from scripts import rc022_manager_update_probe as probe
    monkeypatch.setattr(probe,'corpus',lambda:['live'])
    original=CurrentPluginManager.removeBundle
    def refuse(self,name):
        async def fail():raise RuntimeError('write lock refused')
        return fail()
    monkeypatch.setattr(CurrentPluginManager,'removeBundle',refuse)
    row=(await observe(tmp_path))[0]
    assert row['result']['step']=='remove'
    assert row['result']['result']['error']==dict(code='operation-error',diagnostic='write lock refused')
    assert row['probe']=='1.0.0' and row['dependencies']=={'fresh':'1.0.0'}
    monkeypatch.setattr(CurrentPluginManager,'removeBundle',original)
