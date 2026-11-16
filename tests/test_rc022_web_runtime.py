import asyncio
import json
from pathlib import Path

import pytest

from dsh.bundle.web_app import current
from dsh.cordis.awaiting import await_callback_result
from scripts.rc022_candidate_fixture import setup
from test_rc022_manager_wire import http


@pytest.mark.asyncio
@pytest.mark.parametrize('public',[None,'HTTPS://APP.EXAMPLE:443/ui'])
async def test_actual_loader_advertised_origin_static_owner_and_separate_context(tmp_path, monkeypatch, public):
    index=tmp_path/'index.html';index.write_text('<html><head></head><body>runtime-shell</body></html>',encoding='utf-8')
    assert Path(current.resolve_dist_index()).name=='index.html'
    monkeypatch.setattr(current,'resolve_dist_index',lambda:str(index))
    ctx=await setup(tmp_path,extra=[('credentials-local',dict(path=str(tmp_path/'credentials.yml'))),
        ('typert-registry',{}),('api-remote-access',{}),('client-connection',{}),
        ('host-webserver',dict(host='127.0.0.1',port=0)),('shell-env',{}),
        ('web-app',dict(openBrowser=False,printUrl=False,publicUrl=public)),('harness-dev-context',{})])
    lease=None
    try:
        advertised='https://app.example/ui/' if public else ctx.webServer.getOrigin()
        assert ctx.webApp.getAdvertisedUrl()==advertised
        assert ctx.get('webRuntime') is None
        assert (await http(ctx.webServer,'/'))['status']==401
        exchange=await http(ctx.webServer,'/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        cookie=exchange['headers']['set-cookie'].split(';')[0]
        # read_resource also exercises the original current peer-aware fallback.
        response=await ctx.webServer.readResource(dict(url='/',method='GET',headers={'cookie':cookie,'host':'127.0.0.1:'+str(ctx.webServer.port)}),ctx.connection.browserPeer)
        assert response['status']==200 and b'runtime-shell' in response['body']
        assert b'<base href="./">' in response['body']
        contributor=ctx.shellEnv._contributors['web-runtime']
        assert contributor['resolve']()['DSH_WEB_URL']==advertised
        lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='m')))
        prompt=await ctx.systemPrompt.assemble(dict(agent=lease.agent,scope=lease.agent.ctx))
        assert len([row for row in prompt['sections'] if row['name']=='app:web-surface'])==1
        assert advertised in next(row['text'] for row in prompt['contexts'] if row['name']=='app:web-surface')
        entry=next(entry for entry in ctx.loader.entries() if entry.options.get('id')=='web-app')
        await await_callback_result(ctx.loader.update(entry.id,dict(disabled=True)))
        assert ctx.get('webApp') is None and 'web-runtime' not in ctx.shellEnv._contributors
        assert (await http(ctx.webServer,'/'))['status']==404
        (tmp_path/'web-runtime-observations.json').write_text(json.dumps(dict(public=public,advertised=advertised,indexStatus=response['status'],base=True,unloaded=True),indent=2),encoding='utf-8')
    finally:
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,ssh',[(False,False),(True,False),(False,True)])
async def test_runtime_announces_only_after_loader_audit_and_suppresses_ssh_handoff(tmp_path,monkeypatch,capsys,failure,ssh):
    gate=asyncio.Event();entered=asyncio.Event();opened=[]
    original=current.audit_startup_entries
    async def audit(*args):
        entered.set();await gate.wait()
        if failure:raise RuntimeError('controlled sibling startup failure')
        await original(*args)
    async def opener(url):opened.append(url)
    monkeypatch.setenv('SSH_CONNECTION','ssh-present' if ssh else '')
    monkeypatch.setenv('SSH_TTY','')
    monkeypatch.setattr(current,'audit_startup_entries',audit)
    monkeypatch.setattr(current,'open_browser',opener)
    ctx=await setup(tmp_path,extra=[('credentials-local',dict(path=str(tmp_path/'credentials.yml'))),
        ('typert-registry',{}),('api-remote-access',{}),('client-connection',{}),
        ('host-webserver',dict(host='127.0.0.1',port=0)),
        ('web-app',dict(openBrowser=True,printUrl=True,surfaceContext=False,publicUrl='https://app.example/ui'))])
    try:
        await asyncio.wait_for(entered.wait(),3)
        assert not opened and 'dsh web:' not in capsys.readouterr().out
        gate.set()
        for _ in range(20):await asyncio.sleep(0)
        output=capsys.readouterr().out
        if failure:assert not opened and 'dsh web:' not in output
        else:
            assert 'dsh web: https://app.example/ui/' in output
            assert len(opened)==(0 if ssh else 1)
            if opened:assert opened[0].startswith('https://app.example/ui/') and 'token=' in opened[0]
        assert ctx.get('webApp') is not None
    finally:await ctx.fiber.dispose()
