import asyncio
import json
import sys

import pytest

from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.typert.artifact import read_generated_artifact
from scripts.rc022_candidate_fixture import setup
from test_rc022_manager_wire import http,WireClient,SOURCE


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Canonical Windows Job and PowerShell carrier')
async def test_loader_shell_job_actual_generated_remote_and_model_cursor(tmp_path):
    extra=[('subprocess-local',{}),('pwsh-local',dict(cwd=str(tmp_path))),('shell-env',{}),('jobs-local',dict(pumpPollMs=5)),('tool-pwsh',{}),('tool-jobs',dict(completionDelivery='quiet')),
        ('typert-registry',{}),('api-remote-access',{}),('api-gateway',dict(websocketCompression='none')),('api-remotes',{}),('credentials-local',dict(path=str(tmp_path/'credentials.yaml'))),('client-connection',{}),('api-job-controller',dict(observeFlushMs=1)),('host-webserver',dict(host='127.0.0.1',port=0))]
    def prepare(ctx):
        ctx.inject(['typert'],lambda child:child.effect(lambda:child.typert.register(read_generated_artifact(SOURCE/'packages/api/job-controller/lib/typert.host.js'))))
    ctx=await setup(tmp_path,extra=extra,prepare=prepare);lease=None;client=None;subprocess=ctx.subprocess
    async def rpc(args):
        response=await http(ctx.webServer,'/api/job/kill',dict(type='client-request',rpcId='kill',method='job/kill',payload=dict(args=dict(request=args))),cookie)
        assert response['status']==200,response
        return json.loads(response['body'])
    try:
        lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='model')))
        assert ctx.shellEnv.list()==[]
        result=await ctx.tools.execute(ToolExecutionInput('run','pwsh',dict(command="[Console]::Write('head'); Start-Sleep -Seconds 30",description='Owned background output',run_in_background=True),agent=lease.agent,signal=NEVER_ABORTED))
        assert not result.is_error,(result.content,result.error)
        assert result.value['kind']=='background';identity=result.value['jobId']
        response=await http(ctx.webServer,'/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        cookie=response['headers']['set-cookie'].split(';')[0]
        client=await WireClient().connect(ctx.webServer.listened_port,cookie=cookie)
        await client.send(dict(type='open',streamId='output',endpoint='job/follow',payload=dict(args=dict(request=dict(jobId=identity,sessionId='owner')))))
        frames=[]
        while not any(frame.get('value',{}).get('type')=='output' for frame in frames):frames.append(await client.receive())
        assert frames[0]['type']=='item' and frames[0]['value']['type']=='opened',frames
        refused=await rpc(dict(jobId=identity,sessionId='foreign'))
        assert refused['result']['error']['code']=='job/not-found',refused
        killed=await rpc(dict(jobId=identity,sessionId='owner'))
        assert killed['result']['value']==dict(outcome='requested'),killed
        await asyncio.wait_for(ctx.jobs.wait(identity,10000,'owner'),12)
        while frames[-1]['type']!='end':frames.append(await client.receive())
        assert any(frame.get('value',{}).get('type')=='status' and frame['value']['job']['status']=='killed' for frame in frames)
        assert not ctx.subprocess.live
        assert ctx.jobs.store[identity]['modelCursor']==0 and not ctx.jobs.store[identity]['resultDelivered']
        model=ctx.jobs.read(identity,'owner');assert 'head' in ''.join(chunk['text'] for chunk in model['chunks'])
        (tmp_path/'shell-job-wire-observations.json').write_text(json.dumps(dict(background=result.value,frames=frames,foreign=refused,kill=killed,model=model),indent=2),encoding='utf-8')
    finally:
        if client is not None:await client.close()
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()
    assert not subprocess.live
