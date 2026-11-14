"""Pair complete profile generations, publication order and preapply recovery."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_resolution_probe import package
OUTPUT=None
MODES=['unchanged','retry','running','running-failed','remove','held','group','restart','publish-error','read-error']


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(MODES),encoding='utf-8');return [path]


def fixture(directory):
    home=directory/'home';active=home/'profiles/active'
    anchor=package(directory/'installation','installation')
    package(active,'profile',dependencies={'selected':'*'},dsh=dict(profile=dict(bundles=['selected'])))
    selected=active/'node_modules/selected'
    package(selected,'selected',dependencies={'private':'*'},dsh=dict(bundle=dict(patch='./patch.yml')))
    (selected/'patch.yml').write_text('[]',encoding='utf-8')
    package(selected/'node_modules/private','private')
    path=active/'root.json';path.write_text('[]',encoding='utf-8')
    return dict(installAnchor=str(anchor),home=str(home),profile=dict(name='active',dir=str(active),layers=[dict(packageName='selected',packageDir=str(selected),patches=[],patchPaths=[])],skippedBundles=[])),path


async def native():
    from dsh.boot import boot,recompose_profile,PluginPackages,create_runtime_resolution
    result=[];raw=[]
    for mode in MODES:
        directory=OUTPUT/'files/native'/mode;options,path=fixture(directory)
        resolution=await create_runtime_resolution(options)
        trace=[];reload=[];entered=asyncio.Event();release=asyncio.Event();holder={}
        row=dict(id='candidate',name='cordis:broken' if mode=='running-failed' else 'cordis:absent' if mode=='retry' else 'cordis:held')
        rows=[dict(id='first',name='cordis:healthy'),row,dict(id='last',name='cordis:healthy')]
        if mode=='group':rows=[dict(id='group',name='cordis:group',group=True,config=[row])]
        patches=[dict(insert=rows)]
        def setup(ctx):
            service=PluginPackages(ctx,dict(resolution=resolution));holder['packages']=service
            original=service.replace
            def replace(value):
                trace.append('publish')
                if mode=='publish-error':raise RuntimeError('publication failed')
                original(value)
            service.replace=replace
            def healthy(owner,config):pass
            def broken(owner,config):raise RuntimeError('candidate activation failed')
            def held(owner,config):
                trace.append('start')
                async def cleanup():
                    trace.append('stop-old' if any(entry['name']=='private' for entry in holder['packages'].resolution.entries) else 'stop-new')
                    entered.set()
                    if mode=='held':await release.wait()
                owner.effect(lambda:cleanup)
            ctx.loader.builtins.update(healthy=healthy,broken=broken,held=held)
            ctx.on('app-boot/config-reload',lambda *args:reload.append(list(args)))
        warning=io.StringIO()
        with contextlib.redirect_stderr(warning):ctx=await boot('probe',str(path),patches,setup)
        try:
            before=next(row for row in ctx.loader.entries() if row.options['id']=='candidate')
            fiber=before.fiber;running=[]
            if mode=='retry':ctx.loader.builtins['absent']=lambda owner,config:None
            if mode.startswith('running'):
                running=[before]
                ctx.registry.delete(before.fiber.runtime.callback)
                await asyncio.gather(before.fiber.await_(),return_exceptions=True);await ctx.loader.await_()
            removing=mode in ('remove','held','group','restart','publish-error','read-error')
            next_patches=[] if mode=='group' else [dict(insert=[rows[0],rows[-1]])] if removing else patches
            if removing:
                selected=Path(options['profile']['layers'][0]['packageDir'])/'package.json'
                manifest=json.loads(selected.read_text(encoding='utf-8'));manifest['dependencies']={};selected.write_text(json.dumps(manifest),encoding='utf-8')
            if mode=='restart':
                anchor=Path(options['installAnchor']);manifest=json.loads(anchor.read_text(encoding='utf-8'));manifest['version']='2.0.0';anchor.write_text(json.dumps(manifest),encoding='utf-8')
            if mode=='read-error':Path(options['installAnchor']).write_text('{',encoding='utf-8')
            trace.clear();error=None;answer=None;settled_before=None
            operation=asyncio.create_task(recompose_profile(ctx,next_patches,'probe',dict(running=running)))
            if mode=='held':await asyncio.wait_for(entered.wait(),3);settled_before=operation.done();release.set()
            try:
                with contextlib.redirect_stderr(warning):answer=await operation
            except Exception as failure:error=str(failure)
            after=next((row for row in ctx.loader.entries() if row.options['id']=='candidate'),None)
            result.append(dict(mode=mode,fatal=error is not None,restart=None if answer is None else answer.get('restartReason'),
                warnings=None if answer is None else len(answer['warnings']),same_entry=before is after,same_fiber=after is not None and fiber is after.fiber,
                active=after is not None and after.fiber is not None and after.fiber.state==2,
                candidate=after is not None,ids=[row.options['id'] for row in ctx.loader.entries() if row.options['id'] in ('first','candidate','last','group')],
                trace=list(trace),reload=reload,settled_before=settled_before,old_table=holder['packages'].resolution is resolution))
            raw.append(dict(mode=mode,error=error,answer=answer,log=warning.getvalue(),options=None if after is None else after.options,
                state=None if after is None or after.fiber is None else after.fiber.state,uid=None if after is None or after.fiber is None else after.fiber.uid))
        finally:
            release.set()
            with contextlib.redirect_stderr(warning):await ctx.fiber.dispose()
    (OUTPUT/'native-diagnostics.json').write_text(json.dumps(raw),encoding='utf-8');return result


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_recompose.mts','Complete recomposition order, package publication/restart, retry and preapply restoration; no launcher watcher claim.',
        [Path(__file__).resolve(),ROOT/'dsh/boot/recomposition.py'],prepare,node_args=('--expose-internals',))
