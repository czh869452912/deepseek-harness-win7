import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from dsh.boot.plugin_inspection import _map_concurrent, PluginInspection
from dsh.boot.plugin_package_view import read_profile_registry
from scripts.rc022_manager_inspection_probe import observe


@pytest.mark.asyncio
async def test_actual_manager_metadata_reads_retries_and_versions(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert all(row['remote'] for row in rows.values())
    assert rows['registries']['result']['resolved']=='https://corp.example/npm'
    assert rows['registry-invalid']['result']['resolved'] is None
    assert rows['registry-exit']['result']['resolved'] is None
    assert rows['invalid']['result']['problem']=='invalid-spec'
    assert rows['local-array-bundle']['result']['bundle'] is True
    assert rows['local-known']['result']['problem']=='already-installed'
    assert rows['registry-array']['result']['name']=='last'
    assert rows['registry-empty']['result']['problem']=='unknown'
    assert rows['fallback']['result']['status']=='accepted'
    assert len(rows['fallback']['queries'])==2
    assert len(rows['private']['queries'])==1
    assert len(rows['explicit-private']['queries'])==1
    assert len(rows['permission-no-retry']['queries'])==1
    assert rows['pre-cancel']['queries']==[]
    assert len(rows['caller-cancel']['queries'])==1
    assert rows['timeout']['result']['problem']=='network'
    listed=rows['versions']['result']
    assert listed['status']=='listed' and listed['omitted']==1
    assert [row['version'] for row in listed['versions']]==['4.0.0','3.0.0-beta.1','2.0.0']
    assert listed['versions'][0]['incompatible']['requirements']=={'engines.dsh':'>=99.0.0'}
    assert listed['versions'][0]['deprecated']=='old'
    assert not listed['versions'][2]['bundle']
    assert 'incompatible' not in rows['versions-exempt']['result']['versions'][0]
    assert rows['versions-failed-detail']['result']['problem']=='not-found'
    assert len(rows['versions-failed-detail']['queries'])==2
    assert rows['versions-origin']['queries'][0]['registry']=='https://origin.example/'


@pytest.mark.asyncio
async def test_concurrent_lookup_preserves_index_order_and_stops_unstarted_items():
    started=[];release=asyncio.Event();second=asyncio.Event()
    async def operation(item):
        started.append(item)
        if item==0:
            await release.wait()
            return dict(status='read',version=0)
        second.set()
        return dict(status='refused',problem='failed')
    task=asyncio.create_task(_map_concurrent(list(range(5)),2,operation))
    await second.wait();await asyncio.sleep(0)
    release.set();result=await task
    assert started==[0,1]
    assert result[0]['status']=='read' and result[1]['status']=='refused'
    assert result[2:]==[None,None,None]


def test_explicit_package_options_and_registry_origin_do_not_merge_defaults():
    manager=PluginInspection();manager.pnpm_command='custom';manager.profile=NS(packageManager={});manager.installed_from={'pkg':'https://prior.example/'}
    assert manager._package_options()=={}
    from dsh.boot.plugin_registry_policy import UNSPECIFIED
    assert manager._registry_for('pkg',UNSPECIFIED)=='https://prior.example/'
    assert manager._registry_for('pkg',None) is None
    manager.profile=NS(packageManager=None)
    assert manager._package_options()==dict(command='custom')


def test_backend_command_override_and_held_update_scope():
    import contextvars
    manager=PluginInspection();manager.pnpm_command='pnpm';manager.profile=NS(packageManager=None)
    backend=NS(package_options=lambda:dict(command='native',args=['private']))
    values={'profilePackages':backend};manager.owner_context=NS(get=values.get)
    manager.package_backend_scope=contextvars.ContextVar('test_package_backend',default=None)
    assert manager._package_options()==dict(command='native',args=['private'])
    token=manager.package_backend_scope.set(backend)
    values.clear()
    try:
        assert manager._package_backend() is backend
        manager.pnpm_command='custom'
        assert manager._package_backend() is None and manager._package_options()==dict(command='custom')
        manager.profile=NS(packageManager={})
        assert manager._package_options()=={} and manager._package_backend() is None
    finally:manager.package_backend_scope.reset(token)
    manager.pnpm_command='pnpm';manager.profile=NS(packageManager=None)
    assert manager._package_backend() is None


@pytest.mark.asyncio
async def test_registry_query_uses_exact_command_and_last_line(tmp_path):
    script=tmp_path/'registry.py'
    script.write_text('import sys\nassert sys.argv[1:]==["prefix","config","get","registry"]\nprint("notice\\nhttps://example.com/npm")\n',encoding='utf-8')
    result=await read_profile_registry(str(tmp_path),dict(command=sys.executable,args=[str(script),'prefix'],timeoutMs=2000))
    assert result=='https://example.com/npm'
