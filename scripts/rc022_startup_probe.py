"""Real boot policy against the unchanged fixed upstream host."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
MODES=('optional','required','pending','isolated','missing','root','disabled','bounded')


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text('{}',encoding='utf-8');return [path]


async def native():
    from dsh.boot.app_boot import boot
    from dsh.boot.startup import StartupError,capture_startup_composition
    result={}
    for mode in MODES:
        directory=OUTPUT/'files'/'native'/mode;directory.mkdir(parents=True)
        path=directory/'root.json'
        row=dict(id='agent-loop' if mode in ('required','pending','isolated','bounded') else 'optional',name='cordis:broken',config={'privateValue':'do-not-export'})
        if mode in ('pending','isolated','bounded'):row['name']='cordis:waiting'
        if mode=='missing':row['name']='cordis:not-installed'
        if mode=='disabled':row.update(id='agent-loop',disabled=True)
        rows=[row,dict(id='healthy',name='cordis:healthy')]
        if mode=='bounded':rows.extend(dict(id='disabled-'+str(i),name='cordis:healthy',disabled=True) for i in range(257))
        path.write_text('{' if mode=='root' else json.dumps(rows),encoding='utf-8')
        owner=[]
        def setup(ctx):
            owner.append(ctx)
            def broken(host,config):
                error=RuntimeError('boom');error.stack='boom';raise error
            def healthy(host,config):
                if mode=='required':
                    host.effect(lambda: lambda: host.logger.warn('cleanup warning'))
            def waiting(host,config):pass
            waiting.inject=['absent'+str(i) for i in range(257)] if mode=='bounded' else ['absent']
            ctx.loader.builtins.update(broken=broken,healthy=healthy,waiting=waiting)
            if mode=='isolated':ctx.isolate('absent').provide('absent',{})
        failure=None
        warnings=io.StringIO()
        with contextlib.redirect_stderr(warnings):
            try:ctx=await boot('probe',str(path),prepare=setup)
            except StartupError as error:failure=error;ctx=owner[0]
        try:
            composition=failure.composition if failure is not None else capture_startup_composition(ctx)
            for plugin in composition['plugins']:plugin['source']=plugin['source'].replace(directory.as_uri(),'$ROOT')
            entry_rows=[] if failure is None else [dict(id=r['id'],module=r['module'],required=r['required'],fiberState=r['fiberState'],kind=r['outcome']['kind'],phase=r['outcome'].get('phase')) for r in failure.entries]
            result[mode]=dict(fatal=failure is not None,composition=composition,entries=entry_rows,
                disposed=ctx.get('loader') is None,private='do-not-export' in json.dumps(composition),
                original_cause=failure is not None and getattr(failure.__cause__,'message',None)=='Plugin activation failures',
                startup_path=failure is not None and failure.startup['configurationPath']==str(path))
            if mode=='required':
                result[mode]['cleanup_log']=any(message['args'][0]=='cleanup warning' for message in failure.startup['messages'])
            if mode=='optional':
                result[mode]['warning']=warnings.getvalue()
        finally:await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_startup.mts',prepare=prepare,scope='Actual boot required/optional policy, disabled entries, import/root errors, isolation and bounded configuration-free diagnostics retained after teardown.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/boot/startup.py',ROOT/'dsh/boot/app_boot.py',ROOT/'reference/packages/boot/app-boot/src/index.ts',ROOT/'reference/packages/boot/app-boot/src/startup-diagnostics.ts'])
