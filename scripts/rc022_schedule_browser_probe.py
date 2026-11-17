"""Unchanged fixed Web client against the actual candidate Native Schedule."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_application_probe as application
from scripts.rc022_schedule_application_probe import before as configure_model


async def before(ctx,result,output):
    from dsh.host.browser_compat.plugin import BrowserCompatibilityPlugin
    await ctx.plugin(BrowserCompatibilityPlugin)
    await configure_model(ctx,result,output)


async def after(ctx,result,output):
    entry=await ctx.schedule.create(dict(title='Browser Schedule contract',prompt='Perform the browser check',
        timing=dict(kind='after',after_seconds=3600),target=dict(kind='session',sessionId='candidate-minimal')),'candidate-minimal')
    server=ctx.webServer;config=output/'browser-config.json'
    from dsh.core.abort import NEVER_ABORTED
    from dsh.typert.dispatch import original_of
    original=original_of(ctx.schedule);binding=original.typertRemote
    result['scheduleBinding']=dict(type=type(original).__name__,name=original.name,serviceKey=binding['serviceKey'],namespace=binding['namespace'],same=binding['service'] is original)
    from dsh.typert.dispatch import binding_of
    result['bindingDiagnostics']=[]
    for key,receiver in ctx.typertGateway.resolver._services():
        if getattr(original_of(receiver),'typertRemote',None) is None:continue
        try:binding_of(receiver,key,'diagnostic')
        except Exception as error:result['bindingDiagnostics'].append(dict(key=key,type=type(original_of(receiver)).__name__,error=str(error)))
    result['scheduleStrict']=ctx.typert.local.get('schedule/catalog') is not None
    preflight={}
    for endpoint,payload in [('schedule/catalog',{}),('schedule/deliveryLimits',{}),('schedule/view',dict(request=dict(id=entry['id'])))]:
        reply=await ctx.typertGateway.dispatch_rpc(endpoint,dict(args=payload),NEVER_ABORTED,ctx.connection.browserPeer)
        preflight[endpoint]=dict(ok=reply.get('ok'),**(dict(error=reply['error']) if 'error' in reply else {}))
    result['remotePreflight']=preflight
    (output/'remote-preflight.json').write_text(json.dumps(dict(binding=result['scheduleBinding'],invalid=result['bindingDiagnostics'],strict=result['scheduleStrict'],calls=preflight),indent=2),encoding='utf-8')
    config.write_text(json.dumps(dict(url=ctx.connection.authenticatedUrl(server.getOrigin()),task=entry['id'])),encoding='utf-8')
    source=ROOT/'.goose/out/rc022-prep-20261114-01/source'
    rendered=server.renderIndex((source/'apps/web/dist/index.html').read_text(encoding='utf-8'),ctx.connection.browserPeer)
    result['renderedIndexBytes']=len(rendered.encode('utf-8'))
    node=ROOT/'.goose/out/rc022-prep-20261114-01/toolchain/node-v24.9.0-win-x64/node.exe'
    command=[str(node),str(ROOT/'scripts/oracles/rc022_schedule_browser.mjs'),str(source),str(output)]
    result['browserScriptSha256']=hashlib.sha256(Path(command[1]).read_bytes()).hexdigest()
    (output/'browser-command.json').write_text(json.dumps(command),encoding='utf-8')
    process=await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
    try:log=await asyncio.wait_for(process.communicate(),90)
    except BaseException:
        if process.returncode is None:process.kill()
        await process.communicate();raise
    finally:config.unlink()
    (output/'browser.log').write_bytes(log[0])
    result['browser']=json.loads((output/'browser-observations.json').read_text(encoding='utf-8'))
    result['browserTask']=await ctx.schedule.view(dict(id=entry['id']))
    assert process.returncode==0 and result['browser']['passed']
    task=result['browserTask'];assert task['title']=='Browser Schedule edited' and task['prompt']=='Edited by original browser'
    assert task['status']=='active' and task['scheduledAt']==entry['scheduledAt']
    receipt=task['lastDelivery'];agent=ctx.agents.get(receipt['targetSessionId'])
    await asyncio.wait_for(agent.whenIdle(),15);await ctx.sessions.flush(agent.session)
    observed=await ctx.sessionQuery.observeSession(agent.session.id,dict(projectionMode='none'))
    try:
        messages=[event['data'] for event in observed.events if event['type']=='user/message' and event['data'].get('source',{}).get('kind')=='schedule' and event['data']['id']==receipt['messageId']]
        result['browserPersistedDelivery']=dict(receipt=receipt,messages=messages,history=await ctx.schedule.history(dict(id=entry['id'],limit=10)))
        assert len(messages)==1
    finally:observed.dispose()


if __name__=='__main__':
    application.PLATFORM_PATCHES=[str(ROOT/'migration/candidates/rc022/win7-runtime.patch.yml')]
    application.BEFORE_SESSIONS=before;application.AFTER_SESSIONS=after
    raise SystemExit(application.main())
