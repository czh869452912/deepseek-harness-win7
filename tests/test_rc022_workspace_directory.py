import asyncio
import sys

import pytest

from dsh.api.workspace_current import CurrentWorkspaceController
from dsh.api.workspace_directory_current import default_workspace_directory
from dsh.core.abort import AbortController
from dsh.core.session.json import UNDEFINED
from scripts.rc022_workspace_directory_probe import observe
from tests.test_rc022_workspace_remote import remote
from tests.test_rc022_workspace_default import host


@pytest.mark.asyncio
async def test_documents_and_actual_default_remote_observations(tmp_path):
    rows=await observe(tmp_path);assert len(rows)==18
    assert rows[-2]['title']=='default-workspace' and rows[-2]['same'] and rows[-2]['sessions']==0
    assert rows[-1]['absent']


@pytest.mark.asyncio
async def test_windows_hidden_lookup_uses_powershell2_compatible_utf8_and_no_directory_creation():
    calls=[]
    async def run(command,args,signal,visibility):calls.append((command,args,visibility));return dict(stdout='D:\\文档\r\n',stderr='')
    result=await default_workspace_directory(None,AbortController().signal,dict(platform='win32',run=run))
    assert result=='D:\\文档\\deepseek-harness\\default-workspace'
    command,args,visibility=calls[0]
    assert command=='powershell.exe' and visibility=='hidden'
    assert 'New-Object System.Text.UTF8Encoding' in args[-1] and '::new' not in args[-1]
    assert 'DoNotVerify' in args[-1]


@pytest.mark.asyncio
async def test_default_remote_caller_abort_and_timeout_leave_retryable_state(remote,tmp_path,monkeypatch):
    remote.host.live.clear();controller=remote.controller;controller.config['documentsLookupTimeoutMs']=10
    entered=asyncio.Event()
    async def held(directory,signal):entered.set();await signal.wait_aborted();signal.throwIfAborted()
    monkeypatch.setattr('dsh.api.workspace_current.default_workspace_directory',held)
    with pytest.raises(TimeoutError):await controller.initializeDefault(AbortController().signal)
    assert 'defaultWorkspaceId' not in remote.host.registry._state
    entered.clear();controller.config['documentsLookupTimeoutMs']=10000;caller=AbortController()
    work=asyncio.create_task(controller.initializeDefault(caller.signal));await entered.wait()
    reason=RuntimeError('caller ended');caller.abort(reason)
    with pytest.raises(RuntimeError) as caught:await work
    assert caught.value is reason and 'defaultWorkspaceId' not in remote.host.registry._state
    async def resolved(directory,signal):signal.throwIfAborted();return str(tmp_path/'default-workspace')
    monkeypatch.setattr('dsh.api.workspace_current.default_workspace_directory',resolved)
    first=await controller.initializeDefault(AbortController().signal)
    aborted=AbortController();aborted.abort()
    assert await controller.initializeDefault(aborted.signal)==first
    await controller.delete(dict(workspaceId=first['workspace']['workspaceId']))
    assert await controller.initializeDefault(aborted.signal) is UNDEFINED


@pytest.mark.asyncio
async def test_actual_native_lookup_cancellation_reaps_process(tmp_path):
    from dsh.host.native_command_current import run_native_command
    signal=AbortController()
    task=asyncio.create_task(run_native_command(sys.executable,['-c','import time; time.sleep(30)'],signal.signal))
    # Let process creation settle; cancellation is also safe if it wins startup.
    await asyncio.sleep(.1);reason=RuntimeError('stop lookup');signal.abort(reason)
    with pytest.raises(RuntimeError) as caught:await asyncio.wait_for(task,3)
    assert caught.value is reason


@pytest.mark.parametrize('value',[0,-1,1.5,'100'])
def test_lookup_deadline_configuration_requires_positive_integer(value):
    with pytest.raises(Exception):CurrentWorkspaceController.Config(dict(documentsLookupTimeoutMs=value))
