"""Declared-source HTTP authorization, cold fork workspace and teardown."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from dsh.api.workspace_files_current import CurrentWorkspaceFiles
from dsh.client.ui_deliverables_current import CurrentClientUiDeliverables
from dsh.core.abort import AbortController
from dsh.fs.fs_local import FsLocalPlugin
from dsh.host.connection.current import CurrentHostConnection
from dsh.host.connection.http_current import current_bridge_handler
from dsh.host.webserver.webserver import WebServerService
from scripts.oracles.present_open_current_python import execute
from scripts.session_format_oracle import json_equal
from tests.test_session_agents_current import api_harness

CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/present_open_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_actual_source_declared_native_action(case):
    assert json_equal(execute(case),case['expected'])


async def fixture(tmp_path, connection_class=CurrentHostConnection):
    parent_dir,child_dir=tmp_path/'parent',tmp_path/'child';parent_dir.mkdir();child_dir.mkdir()
    (parent_dir/'output.docx').write_bytes(b'parent');(child_dir/'output.docx').write_bytes(b'child')
    ctx,unused=await api_harness(tmp_path)
    await ctx.plugin(FsLocalPlugin,dict(cwd=str(parent_dir)))
    ctx.set_service('sandboxPolicy',SimpleNamespace(workspaceRoot=str(parent_dir)))
    await ctx.plugin(CurrentWorkspaceFiles)
    parent=await ctx.get('agents').create(dict(sessionId='parent',options=dict(provider='script',model='model'),meta=dict(cwd=str(parent_dir))))
    parent.agent.session.append('turn/start',dict(turn=1))
    delivery=parent.agent.session.append('deliverables/presented',dict(turn=1,callId='present',files=[dict(path='output.docx')]))
    parent.agent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
    seed=list(parent.agent.session.snapshotEvents())
    child=await ctx.get('agents').create(dict(sessionId='child',options=dict(provider='script',model='model'),seed=seed,inheritedEventCount=len(seed),meta=dict(cwd=str(child_dir),parentSession='parent',isSeeded=True)))
    await child.dispose();await parent.dispose()
    calls=[]
    async def opener(request,signal):calls.append((request,signal))
    ctx.set_service('sessionController',SimpleNamespace(workspaceDesktop=lambda:dict(name='serving host',available=True,fileManager='explorer'),openWorkspacePath=opener))
    authenticated=[True]
    connection=connection_class(ctx,[],SimpleNamespace(is_authenticated=lambda *_:authenticated[0],authenticate_api=lambda *_:None))
    fiber=await ctx.plugin(CurrentClientUiDeliverables)
    return ctx,fiber,connection,calls,authenticated,child_dir,delivery['seq']


@pytest.mark.asyncio
async def test_actual_tcp_auth_cold_inherited_file_uses_viewed_child_current_source(tmp_path):
    ctx,fiber,connection,calls,authenticated,child_dir,seq=await fixture(tmp_path)
    server=WebServerService(ctx,host='127.0.0.1',port=0)
    server.register('prefix','/api',current_bridge_handler(connection,connection.createSharedFetchHandler('/api')))
    await server.start()
    async def fetch(path,method='POST'):
        reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
        try:
            writer.write((method+' '+path+' HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n').encode('ascii'))
            await writer.drain()
            raw=await asyncio.wait_for(reader.read(),5)
            headers,body=raw.split(b'\r\n\r\n',1)
            return headers.lower(),body
        finally:writer.close();await writer.wait_closed()
    url='/api/present.open?'+urlencode(dict(sessionId='child',seq=seq,index=0,action='reveal'))
    try:
        authenticated[0]=False
        assert (await fetch(url))[0].startswith(b'http/1.1 401') and not calls
        authenticated[0]=True
        for data in (b'child now',b'child edited'):
            (child_dir/'output.docx').write_bytes(data)
            headers,body=await fetch(url)
            assert headers.startswith(b'http/1.1 204') and b'cache-control: no-store' in headers and not body
            request,signal=calls[-1]
            assert request==dict(path=str((child_dir/'output.docx').resolve()),action='reveal')
            assert Path(request['path']).read_bytes()==data and not signal.aborted
            assert ctx.get('agents').get('child') is None and ctx.get('agents').get('parent') is None
        headers,body=await fetch('/api/present.host','GET')
        assert headers.startswith(b'http/1.1 200') and json.loads(body)['name']=='serving host'
        count=len(calls);(child_dir/'output.docx').unlink()
        assert (await fetch(url))[0].startswith(b'http/1.1 404') and len(calls)==count
        await fiber.dispose()
        assert (await fetch(url))[0].startswith(b'http/1.1 404')
        assert ctx.get('attachments') is None
    finally:await server.stop();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_disposal_aborts_and_awaits_admitted_launch_then_detaches_caller(tmp_path):
    ctx,fiber,connection,calls,auth,child_dir,seq=await fixture(tmp_path)
    entered,aborted,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    controller=AbortController()
    async def opener(request,signal):
        signal.add_listener('abort',lambda reason:aborted.set())
        entered.set();await release.wait();signal.throwIfAborted()
    ctx.get('sessionController').openWorkspacePath=opener
    request=dict(url='http://localhost/api/present.open?'+urlencode(dict(sessionId='child',seq=seq,index=0)),path='/api/present.open',method='POST',headers={},signal=controller.signal)
    task=asyncio.create_task(connection.createSharedFetchHandler('/api').fetch(request))
    try:
        await asyncio.wait_for(entered.wait(),2)
        disposal=asyncio.create_task(fiber.dispose())
        await asyncio.wait_for(aborted.wait(),2)
        assert not disposal.done() and not controller.signal.aborted
        release.set();await asyncio.wait_for(disposal,2)
        with pytest.raises(Exception,match='aborted'):await task
        assert not controller.signal._listeners and not connection.fetch_routes
        assert (child_dir/'output.docx').read_bytes()==b'child'
    finally:release.set();await asyncio.gather(task,return_exceptions=True);await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_caller_abort_during_launch_preserves_reason_and_route_can_retry(tmp_path):
    ctx,fiber,connection,calls,auth,child_dir,seq=await fixture(tmp_path)
    entered=asyncio.Event();failure=RuntimeError('caller cancelled launch');controller=AbortController()
    async def opener(request,signal):entered.set();await signal.wait_aborted();signal.throwIfAborted()
    ctx.get('sessionController').openWorkspacePath=opener
    request=dict(url='http://localhost/api/present.open?'+urlencode(dict(sessionId='child',seq=seq,index=0)),path='/api/present.open',method='POST',headers={},signal=controller.signal)
    task=asyncio.create_task(connection.createSharedFetchHandler('/api').fetch(request))
    try:
        await asyncio.wait_for(entered.wait(),2);controller.abort(failure)
        with pytest.raises(RuntimeError) as caught:await asyncio.wait_for(task,2)
        assert caught.value is failure and not controller.signal._listeners
        async def retry(request,signal):calls.append((request,signal))
        ctx.get('sessionController').openWorkspacePath=retry
        result=await connection.createSharedFetchHandler('/api').fetch(dict(request,signal=AbortController().signal))
        assert result['status']==204 and len(calls)==1
    finally:await ctx.fiber.dispose()
