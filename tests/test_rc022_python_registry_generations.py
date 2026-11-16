import json
from pathlib import Path

import pytest

from dsh.boot.profile_lease import ProfileLease
from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.boot.python_package_acquire import acquired_registry_package
from dsh.boot.python_plugin_acquisition import verified_record
from dsh.boot import python_plugins as store,python_plugin_versions as versions
from test_python_plugin_distribution import profile,boot,close,EXAMPLE,PACKAGE
from test_rc022_python_package_acquire import registry_package


def manifest(directory):return json.loads((directory/'package.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
async def test_disabled_registry_generations_keep_source_identity_and_restore_without_network(profile,registry_package):
    home,directory=profile;state=registry_package
    with acquired_registry_package(str(directory),PACKAGE,state['url'],state['env']) as candidate:
        old=candidate.acquisition
        store.install(str(directory),candidate.source,INSTALL_ANCHOR,old,enabled=False)
    first=manifest(directory);assert first['dependencies'][PACKAGE]=='0.1.0' and PACKAGE not in first['dsh']['profile']['bundles']
    assert old['name']==PACKAGE and old['version']=='0.1.0' and old['registry']==state['url']+'/'
    result=await boot(home)
    try:
        assert all(row.options.get('id')!='example-python-echo' for row in result['ctx'].loader.entries())
        from dsh.boot.plugin_manager_current import CurrentPluginManager
        from dsh.boot.python_package_cli import package_command
        ctx=result['ctx'];ctx.profileContext['packageManager']=package_command(dict(state['env'],PATH='',npm_config_registry=state['url']))
        await ctx.plugin(CurrentPluginManager)
        row=next(row for row in await ctx.pluginManager.listBundles() if row['name']==PACKAGE)
        assert row['installed'] and not row['enabled'] and row['source']==PACKAGE+'@0.1.0' and row['update']=='registry'
        assert (await ctx.pluginManager.inspect(PACKAGE))['problem']=='already-installed'
    finally:await close(result)
    state['index_version']='0.2.0';state['metadata']['version']='0.2.0';state['pack'](state['metadata'])
    with acquired_registry_package(str(directory),PACKAGE+'@0.2.0',state['url'],state['env']) as candidate:
        new=candidate.acquisition
        # The explicitly owned single-host lease is borrowed through upgrade.
        with ProfileLease(str(directory)) as host:
            with host.exclusive_window():versions.upgrade(str(directory),candidate.source,INSTALL_ANCHOR,new,lease=host)
            assert not host.exclusive and host.stream is not None
    second=manifest(directory);assert second['dependencies'][PACKAGE]=='0.2.0' and PACKAGE not in second['dsh']['profile']['bundles']
    current=second['dsh']['pythonPlugins'][PACKAGE];assert current['acquisition']==new and current['history'][0]['acquisition']==old
    calls=list(state['requests'])
    with ProfileLease(str(directory)) as host:
        with host.exclusive_window():versions.rollback(str(directory),PACKAGE,lease=host)
    restored=manifest(directory);assert restored['dependencies'][PACKAGE]=='0.1.0' and PACKAGE not in restored['dsh']['profile']['bundles']
    assert restored['dsh']['pythonPlugins'][PACKAGE]['acquisition']==old and state['requests']==calls
    store.uninstall(str(directory),PACKAGE)


@pytest.mark.parametrize('damage',['name','version','registry','extra'])
def test_registry_record_fields_cannot_disagree_with_validated_archive(profile,registry_package,damage):
    home,directory=profile;state=registry_package;before=(directory/'package.json').read_bytes()
    with acquired_registry_package(str(directory),PACKAGE,state['url'],state['env']) as candidate:
        record=dict(candidate.acquisition)
        if damage=='name':record['name']='@example/other'
        if damage=='version':record['version']='2.0.0'
        if damage=='registry':record['registry']='https://user:secret@example.invalid/'
        if damage=='extra':record['unknown']='untrusted'
        with pytest.raises(ValueError):store.install(str(directory),candidate.source,INSTALL_ANCHOR,record)
    assert (directory/'package.json').read_bytes()==before and not (directory/'node_modules/@example/python-echo').exists()


def test_changed_registry_reference_refuses_uninstall_before_touching_bytes(profile,registry_package):
    home,directory=profile;state=registry_package
    with acquired_registry_package(str(directory),PACKAGE,state['url'],state['env']) as candidate:store.install(str(directory),candidate.source,INSTALL_ANCHOR,candidate.acquisition)
    changed=manifest(directory);changed['dependencies'][PACKAGE]='file:elsewhere';(directory/'package.json').write_text(json.dumps(changed),encoding='utf-8')
    before=(directory/'package.json').read_bytes();files=store.file_hashes(str(directory/'node_modules/@example/python-echo'))
    with pytest.raises(ValueError,match='references changed'):store.uninstall(str(directory),PACKAGE)
    assert (directory/'package.json').read_bytes()==before and store.file_hashes(str(directory/'node_modules/@example/python-echo'))==files
    changed['dependencies'][PACKAGE]='0.1.0';(directory/'package.json').write_text(json.dumps(changed),encoding='utf-8');store.uninstall(str(directory),PACKAGE)
