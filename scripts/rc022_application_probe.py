"""Boot fixed official application composition on candidate Native providers.

This isolated probe changes installation anchors and additional candidate
bindings only inside its process. It does not promote production inputs/pins.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGET='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
BINDINGS={
 '@deepseek-ai/dsh-schedule':'dsh.schedule.service_current:CurrentScheduleService',
 '@deepseek-ai/dsh-client-modules':'dsh.host.client_modules.current:CurrentClientModulesPlugin',
 '@deepseek-ai/dsh-cordis-host-runner':'dsh.extensions.host_runner_current:CurrentDynamicCordisRunner',
 '@deepseek-ai/dsh-tool-cordis':'dsh.extensions.inspect_tools_current:CurrentCordisInspectTools',
 '@deepseek-ai/dsh-tool-cordis/host':'dsh.extensions.inspect_providers_current:CurrentCordisInspectProviders',
 '@deepseek-ai/dsh-cordis-manager':'dsh.extensions.cordis_manager_current:CurrentNativeCordisManager',
}


async def observe(source,output):
    import dsh
    from dsh.boot import profile_boot
    from dsh.boot.plugin_registry import HARNESS_PLUGIN_CLASSES
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    result={};started=time.monotonic();app=None
    home=output/'home';home.mkdir()
    loop=asyncio.get_running_loop();diagnostic=None
    def dump():
        nonlocal diagnostic
        with (output/'tasks.log').open('a',encoding='utf-8') as log:
            for task in asyncio.all_tasks():
                log.write(repr(task)+'\n');task.print_stack(file=log)
        diagnostic=loop.call_later(20,dump)
    diagnostic=loop.call_later(20,dump)
    with patch.dict(os.environ,dict(DSH_HOME=str(home),DSH_TELEMETRY_MODE='DISABLED')),patch.object(profile_boot,'INSTALL_ANCHOR',str(source/'apps/cli/package.json')),patch.object(dsh,'__version__','0.2.2-rc.3'),patch.dict(HARNESS_PLUGIN_CLASSES,BINDINGS):
        try:
            environment=LaunchEnvironmentSnapshot([dict(source='process',values=dict(os.environ))])
            app=await profile_boot.run_profile(dict(profile='web',dshHome=str(home),environment=environment,
                args=['--host','127.0.0.1','--port','0','--no-open'],waitForExit=False))
            ctx=app['ctx'];result['stage']='booted'
            result['presets']=await ctx.get('agentPresets').remoteExportList()
            result['providers']=ctx.get('cordisInspect').list()
            result['entries']=[dict(id=entry.id,name=entry.options['name'],disabled=entry.disabled,
                state=None if entry.fiber is None else entry.fiber.state) for entry in ctx.loader.entries()]
            modules=ctx.get('clientModules');graph=modules.graph()
            result['clientGraph']=dict(release=graph.get('release'),entries=len(graph['entries']),batches=len(graph['batches']))
            result['resourceChecks']=[]
            for batch in graph['batches']:
                url='http://candidate/'+batch['url'].lstrip('/')
                head=await modules.fetchBundle(dict(method='HEAD',url=url))
                script=await modules.fetchBundle(dict(method='GET',url=url))
                body=script['body']
                result['resourceChecks'].append(dict(phase=batch['phase'],url=batch['url'],headStatus=head['status'],
                    headEmpty=head['body'] is None,status=script['status'],bytes=len(body),sha256=hashlib.sha256(body).hexdigest()))
            for identity in ['minimal','standard','ptc','cordis']:
                try:
                    await ctx.get('sessionController').create(dict(sessionId='candidate-'+identity,cwd=str(output),agentPreset=identity))
                    result.setdefault('sessions',[]).append(dict(preset=identity,status='created'))
                except Exception as error:
                    result.setdefault('sessions',[]).append(dict(preset=identity,error=str(error)))
                    with (output/'session-errors.log').open('a',encoding='utf-8') as log:
                        log.write(identity+'\n');traceback.print_exc(file=log)
        except Exception as error:
            result.update(stage='failed',error=str(error))
            if hasattr(error,'composition'):result['composition']=error.composition
        finally:
            if app is not None:
                app['shutdown'].shutdown(0);await app['shutdown'].wait()
            diagnostic.cancel()
    result['seconds']=time.monotonic()-started
    return result


def main():
    import subprocess
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();output=args.output.resolve()
    output.relative_to(ROOT/'.goose/out');output.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],encoding='utf-8').strip()==TARGET
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],encoding='utf-8').strip()
    result=asyncio.run(observe(source,output))
    result['target_upstream']=TARGET
    result['candidate_bindings']=BINDINGS
    inputs=[source/'apps/cli/package.json',source/'packages/bundle/base/cordis.patch.yml',
        source/'packages/bundle/web-app/package.json',source/'packages/bundle/web-app/cordis.patch.yml',
        source/'packages/client/modules/src/index.ts',source/'packages/client/modules/src/assets.ts',
        Path(__file__).resolve(),ROOT/'dsh/boot/plugin_registry_current.py',
        ROOT/'dsh/cordis/loader.py',ROOT/'dsh/api/session_agents_current.py',
        ROOT/'dsh/host/client_modules/current.py',ROOT/'dsh/host/client_modules/resources_current.py',ROOT/'dsh/host/client_modules/assets_current.py']
    result['input_sha256']={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    result['source_clean_after']=not subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],encoding='utf-8').strip()
    (output/'observations.json').write_text(json.dumps(result,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps(dict(stage=result['stage'],error=result.get('error'),sessions=result.get('sessions'),seconds=result['seconds'])))
    return 0 if result['stage']=='booted' and len(result.get('sessions',[]))==4 and all('error' not in row for row in result['sessions']) else 1


if __name__=='__main__':raise SystemExit(main())
