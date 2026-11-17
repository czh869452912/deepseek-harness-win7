"""Unchanged fixed Web client against the actual candidate Native Schedule."""
import asyncio
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
    config.write_text(json.dumps(dict(url=ctx.connection.authenticatedUrl(server.getOrigin()),task=entry['id'])),encoding='utf-8')
    source=ROOT/'.goose/out/rc022-prep-20261114-01/source'
    rendered=server.renderIndex((source/'apps/web/dist/index.html').read_text(encoding='utf-8'),ctx.connection.browserPeer)
    result['renderedIndexBytes']=len(rendered.encode('utf-8'))
    node=ROOT/'.goose/out/rc022-prep-20261114-01/toolchain/node-v24.9.0-win-x64/node.exe'
    command=[str(node),str(ROOT/'scripts/oracles/rc022_schedule_browser.mjs'),str(source),str(output)]
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


if __name__=='__main__':
    application.PLATFORM_PATCHES=[str(ROOT/'migration/candidates/rc022/win7-runtime.patch.yml')]
    application.BEFORE_SESSIONS=before;application.AFTER_SESSIONS=after
    raise SystemExit(application.main())
