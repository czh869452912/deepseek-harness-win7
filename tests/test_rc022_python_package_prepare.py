import asyncio
import json
from pathlib import Path
import shutil
import threading

import pytest

from dsh.boot.python_package_prepare import prepared_registry_package,read_prepared
from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.boot.profile_lease import ProfileLease
from dsh.boot import python_plugins as store
from dsh.core.abort import AbortController
from test_python_plugin_distribution import profile,EXAMPLE,PACKAGE
from test_rc022_python_package_acquire import registry_package


def options(state):
    certificate=Path(__file__).parent/'fixtures/tls/localhost-cert.pem'
    return dict(registry=state['url'],env=dict(state['env'],PATH='',SSL_CERT_FILE=str(certificate.resolve())),outputBytes=16384,idleTimeoutMs=10000)


@pytest.mark.asyncio
async def test_owned_python_child_prepares_before_host_exclusive_commit(profile,registry_package):
    home,directory=profile;state=registry_package;before=(directory/'package.json').read_bytes();logs=[]
    with ProfileLease(str(directory)) as host:
        async with prepared_registry_package(str(directory),PACKAGE,dict(options(state),onOutput=lambda text,stream:logs.append((text,stream)))) as prepared:
            assert prepared.result['exitCode']==0 and not prepared.result.get('timedOut')
            assert prepared.candidate.manifest['name']==PACKAGE
            assert (directory/'package.json').read_bytes()==before and not host.exclusive
            source=Path(prepared.candidate.source);assert source.is_file()
            with host.exclusive_window():
                store.install(str(directory),str(source),INSTALL_ANCHOR,prepared.candidate.acquisition,lease=host,enabled=False)
        assert not source.exists() and not (directory/'.dsh-python-downloads').exists()
        assert not list(directory.rglob('run.json'))
        assert any('Fetching '+PACKAGE in text for text,stream in logs)
        with host.exclusive_window():store.uninstall(str(directory),PACKAGE,lease=host)


@pytest.mark.asyncio
async def test_failed_python_preparation_never_publishes_candidate(profile,registry_package):
    home,directory=profile;state=registry_package;state['metadata']['dsh'].pop('python');before=(directory/'package.json').read_bytes()
    async with prepared_registry_package(str(directory),PACKAGE,options(state)) as prepared:
        assert prepared.result['exitCode']==1 and prepared.candidate is None
        assert 'ERR_DSH_PYTHON_ABI' in prepared.result['output']
    assert state['requests']==['/@example%2Fpython-echo']
    assert (directory/'package.json').read_bytes()==before and not (directory/'.dsh-python-downloads').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_task',[False,True])
async def test_cancelled_real_download_child_is_drained_and_its_partial_workspace_removed(profile,registry_package,cancel_task):
    home,directory=profile;state=registry_package;state['pause']=threading.Event();state['entered']=threading.Event();control=AbortController();before=(directory/'package.json').read_bytes()
    async def run():
        async with prepared_registry_package(str(directory),PACKAGE,dict(options(state),signal=control.signal)) as prepared:return prepared.result
    task=asyncio.create_task(run())
    try:
        for _ in range(500):
            if state['entered'].is_set():break
            await asyncio.sleep(.02)
        assert state['entered'].is_set()
        if cancel_task:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,3)
        else:
            control.abort();result=await asyncio.wait_for(task,3);assert result['exitCode']==1
        assert (directory/'package.json').read_bytes()==before
        assert not (directory/'.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))
    finally:
        state['pause'].set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('tamper',['archive','receipt','identity','large-receipt','no-acquisition'])
async def test_parent_independently_rejects_modified_child_publication(profile,registry_package,tamper):
    home,directory=profile;state=registry_package;before=(directory/'package.json').read_bytes()
    async with prepared_registry_package(str(directory),PACKAGE,options(state)) as prepared:
        output=Path(prepared.candidate.source).parent;receipt=output/'prepared.json'
        if tamper=='archive':Path(prepared.candidate.source).write_bytes(b'other')
        if tamper=='receipt':receipt.write_text('{}',encoding='utf-8')
        if tamper=='identity':
            value=json.loads(receipt.read_text(encoding='utf-8'));value['manifest']['version']='9.0.0';receipt.write_text(json.dumps(value),encoding='utf-8')
        if tamper=='large-receipt':receipt.write_bytes(b'x'*(1024*1024+1))
        if tamper=='no-acquisition':
            value=json.loads(receipt.read_text(encoding='utf-8'));value['acquisition']=None;receipt.write_text(json.dumps(value),encoding='utf-8')
        with pytest.raises(ValueError):read_prepared(str(output))
    assert (directory/'package.json').read_bytes()==before and not (directory/'.dsh-python-downloads').exists()
