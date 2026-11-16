import asyncio
import json
import sys
from pathlib import Path

import pytest

from scripts.rc022_manager_installation_probe import observe


@pytest.mark.asyncio
async def test_real_install_remove_refusals_fallback_progress_and_activation(tmp_path):
    rows={row['name']:row for row in await asyncio.wait_for(observe(tmp_path),60)}
    assert len(rows)==16
    assert all(row['remotes'] and row['waitSame'] for row in rows.values())
    assert all(row['afterWait'] is None and row['afterCancel']==dict(status='not-running') for row in rows.values())
    assert rows['live']['installed'] and rows['live']['removed']
    assert all(step['application']=='applied' for step in rows['live']['steps'])
    assert rows['startup']['steps'][0]['application']=='restart-required'
    assert rows['disabled']['steps'][0]['enabled'] is False
    assert rows['disabled']['dependencies']=={} and rows['disabled']['selection']==['core']
    assert rows['exact']['dependencies']=={'fresh':'1.0.0'}
    assert rows['fallback']['steps'][0]['registries']==[None,'https://registry.npmmirror.com/']
    assert len(rows['fallback']['states'])==3
    for name,code in [('plain','not-bundle'),('ambiguous','ambiguous-install'),('incompatible','incompatible-version'),('invalid','invalid-spec')]:
        assert rows[name]['steps'][0]['error']['code']==code
        assert not rows[name]['steps'][0]['changed']
        assert rows[name]['lock']=='original\r\n' and rows[name]['dependencies']=={}
    assert rows['build-blocked']['steps'][0]['pendingBuilds']==['builder']
    assert rows['approve']['steps'][0]['approvedBuilds']==['builder']
    cancelled=rows['cancel']
    assert cancelled['cancel']==dict(status='cancelled')
    assert cancelled['steps'][0]['application']=='cancelled'
    assert cancelled['logs'][-1]['exitCode'] is None
    assert cancelled['dependencies']=={} and cancelled['lock']=='original\r\n'
    assert rows['too-late']['tooLate']==[dict(status='too-late')]
    assert rows['activation-error']['steps'][0]['stage']=='enable'
    assert rows['activation-error']['steps'][0]['changed'] and not rows['activation-error']['installed']
    assert rows['repeat-live']['steps'][1]['error']==dict(code='already-installed')
    assert rows['remove-startup']['steps'][1]['error']==dict(code='stop-profile')
    assert rows['incompatible']['facts'][-1]['version']=='1.0.0'
    assert rows['exact']['facts'][-1]['target']=='fresh'


async def waiting_manager(directory):
    from dsh.boot.app_boot import boot
    from dsh.boot.profile_context import read_profile_patches
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')
    home=directory.parent
    write(home/'package.json',dict(name='installation'))
    write(directory/'package.json',dict(name='profile',dependencies={},dsh=dict(profile=dict(bundles=['core']))))
    write(directory/'node_modules/core/package.json',dict(name='core',version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml'))))
    write(directory/'node_modules/core/patch.yml',[dict(insert=[dict(id='manager',name='cordis:manager',config=dict(lockWaitMs=0))])])
    write(directory/'cordis.yml',[]);write(directory/'cordis.patch.yml',[])
    script=directory/'package.py'
    script.write_text('''import json,sys,time
from pathlib import Path
if sys.argv[1]=='config':print('https://registry.npmjs.org/');sys.exit(0)
if sys.argv[1]=='view':print('{}');sys.exit(0)
print('waiting',flush=True)
while not Path('release').exists():time.sleep(.02)
manifest=json.loads(Path('package.json').read_text(encoding='utf-8'))
manifest['dependencies']['fresh']='1.0.0'
Path('package.json').write_text(json.dumps(manifest),encoding='utf-8')
target=Path('node_modules/fresh');target.mkdir(parents=True,exist_ok=True)
(target/'package.json').write_text(json.dumps(dict(name='fresh',version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml')))),encoding='utf-8')
(target/'patch.yml').write_text('[]',encoding='utf-8')
''',encoding='utf-8')
    profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['core'],overlays=[],packageManager=dict(command=str(Path(sys.executable).resolve()),args=[str(script)]))
    def setup(ctx):ctx.provide('profileContext',profile);ctx.loader.builtins['manager']=CurrentPluginManager
    ctx=await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),setup)
    ready=asyncio.Event()
    ctx.on('plugin-manager/install-log',lambda event:ready.set() if 'waiting' in event['text'] else None)
    return ctx,ready


@pytest.mark.asyncio
async def test_cancelling_a_python_waiter_does_not_cancel_owned_installation(tmp_path):
    ctx,ready=await waiting_manager(tmp_path/'profile')
    try:
        manager=ctx.pluginManager;result=manager.installBundle('fresh',dict(requestId='owned'))
        async def wait():return await manager.waitForInstall('owned')
        waiter=asyncio.create_task(wait())
        await asyncio.wait_for(ready.wait(),5)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):await waiter
        assert manager.installs['owned'].result is result and not result.task.done()
        (tmp_path/'profile/release').write_text('release',encoding='utf-8')
        outcome=await asyncio.wait_for(manager.waitForInstall('owned'),5)
        assert outcome['bundle']=='fresh' and outcome['application']=='restart-required'
        assert await result==outcome and not manager.package_operations and not manager.installs
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_owner_disposal_drains_real_package_process_and_installation(tmp_path):
    ctx,ready=await waiting_manager(tmp_path/'profile');manager=ctx.pluginManager
    try:
        promise=manager.installBundle('fresh',dict(requestId='owned'))
        await asyncio.wait_for(ready.wait(),5)
        await asyncio.wait_for(ctx.fiber.dispose(),5)
        result=await asyncio.wait_for(promise,5)
        assert result['application']=='cancelled'
        assert not manager.package_operations and not manager.installs
        assert not list((tmp_path/'profile').rglob('run.json'))
        assert json.loads((tmp_path/'profile/package.json').read_text(encoding='utf-8'))['dependencies']=={}
    finally:await ctx.fiber.dispose()
