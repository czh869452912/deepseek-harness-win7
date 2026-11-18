"""Unchanged fixed Web client against the actual candidate Native Schedule."""
import asyncio
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_application_probe as application
from scripts.rc022_schedule_application_probe import before as configure_model
COLD_FROM = None


async def before(ctx,result,output):
    from dsh.host.browser_compat.plugin import BrowserCompatibilityPlugin
    await ctx.plugin(BrowserCompatibilityPlugin)
    await configure_model(ctx,result,output)


async def after(ctx,result,output):
    result['processId'] = os.getpid()
    old_receipt = None
    if COLD_FROM is None:
        entry=await ctx.schedule.create(dict(title='Browser Schedule contract',prompt='Perform the browser check',
            timing=dict(kind='after',after_seconds=3600),target=dict(kind='session',sessionId='candidate-minimal')),'candidate-minimal')
    else:
        previous=json.loads((COLD_FROM/'comparison/observations.json').read_text(encoding='utf-8'))
        expected=previous['browserTask']
        entry=await ctx.schedule.view(dict(id=expected['id']))
        (output/'cold-task-before.json').write_text(json.dumps(dict(actual=entry,expected=expected),indent=2),encoding='utf-8')
        # This read-time field disappears when its one-minute delivery floor expires.
        assert {key:value for key,value in entry.items() if key!='deliveryFloorEndsAt'}=={
            key:value for key,value in expected.items() if key!='deliveryFloorEndsAt'}, 'cold task differs; see cold-task-before.json'
        if entry.get('deliveryFloorEndsAt')!=expected.get('deliveryFloorEndsAt'):
            assert entry.get('deliveryFloorEndsAt') is None
            assert time.time()>=datetime.fromisoformat(expected['deliveryFloorEndsAt'].replace('Z','+00:00')).timestamp()
        assert previous['processId']!=os.getpid()
        old_receipt=entry['lastDelivery']
        session_id=old_receipt['targetSessionId']
        assert ctx.agents.get(session_id) is None
        observed=await ctx.sessionQuery.observeSession(session_id,dict(projectionMode='none'))
        try:
            (output/'cold-session-before.json').write_text(json.dumps(dict(events=observed.events,
                receipt=old_receipt),ensure_ascii=True,indent=2),encoding='utf-8')
            saved=[event for event in observed.events if event['type']=='user/message' and event['data']['id']==old_receipt['messageId']]
            assert [event['data']['id'] for event in saved]==[old_receipt['messageId']], 'cold Schedule messages differ; see cold-session-before.json'
            result['coldRestart']=dict(sourceRun=COLD_FROM.name,previousProcessId=previous['processId'],
                sessionId=session_id,liveBefore=False,savedMessages=saved,task=entry,
                history=await ctx.schedule.history(dict(id=entry['id'],limit=10)))
            old_events=list(observed.events)
        finally:observed.dispose()
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
    config.write_text(json.dumps(dict(url=ctx.connection.authenticatedUrl(server.getOrigin()),task=entry['id'],cold=COLD_FROM is not None)),encoding='utf-8')
    source=ROOT/'reference'
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
    task=result['browserTask']
    assert task['title']==('Browser Schedule cold edited' if COLD_FROM else 'Browser Schedule edited')
    assert task['prompt']==('Edited after cold process restart' if COLD_FROM else 'Edited by original browser')
    assert task['status']=='active' and task['scheduledAt']==entry['scheduledAt']
    receipt=task['lastDelivery'];agent=ctx.agents.get(receipt['targetSessionId'])
    await asyncio.wait_for(agent.whenIdle(),15);await ctx.sessions.flush(agent.session)
    observed=await ctx.sessionQuery.observeSession(agent.session.id,dict(projectionMode='none'))
    try:
        messages=[event['data'] for event in observed.events if event['type']=='user/message' and event['data'].get('source',{}).get('kind')=='schedule' and event['data']['id']==receipt['messageId']]
        result['browserPersistedDelivery']=dict(receipt=receipt,messages=messages,history=await ctx.schedule.history(dict(id=entry['id'],limit=10)))
        assert len(messages)==1
        if old_receipt is not None:
            all_messages=[event['data'] for event in observed.events if event['type']=='user/message'
                and event['data']['id'] in (old_receipt['messageId'],receipt['messageId'])]
            errors=[event for event in observed.events if event['type'] in ('turn/error','agent/error')]
            assert receipt['messageId']!=old_receipt['messageId']
            assert [message['id'] for message in all_messages]==[old_receipt['messageId'],receipt['messageId']]
            assert not errors
            assert list(observed.events[:len(old_events)])==old_events
            result['coldRestart'].update(liveAfter=ctx.agents.get(agent.session.id) is agent,
                allMessages=all_messages,turnErrors=errors,agentStatus=agent.status,preservedPrefixEvents=len(old_events))
    finally:observed.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--cold-from',type=Path)
    options,remaining=parser.parse_known_args();sys.argv=[sys.argv[0]]+remaining
    if options.cold_from is not None:
        COLD_FROM=options.cold_from.resolve()
        assert COLD_FROM.parent==ROOT/'.goose/out'
        assert json.loads((COLD_FROM/'command.json').read_text(encoding='utf-8'))['exit_code']==0
        previous=json.loads((COLD_FROM/'comparison/observations.json').read_text(encoding='utf-8'))
        assert previous['browser']['passed']
        def prepare(home):
            seed=COLD_FROM/'comparison/home';assert seed.is_dir()
            for path in [seed,*seed.rglob('*')]:
                assert not (getattr(path.lstat(),'st_file_attributes',0)&0x400 or path.is_symlink())
            shutil.copytree(str(seed),str(home),dirs_exist_ok=True)
        application.PREPARE_HOME=prepare;application.SESSION_ID_PREFIX='cold-'
    application.PLATFORM_PATCHES=[str(ROOT/'migration/candidates/rc022/win7-runtime.patch.yml')]
    application.BEFORE_SESSIONS=before;application.AFTER_SESSIONS=after
    raise SystemExit(application.main())
