"""Observe complete-patch reconciliation and owned disposal settlement."""
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
MODES=('unchanged','changed','required','new','pending','required-pending','remove','held','dispose-error','missing','missing-changed')


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(MODES),encoding='utf-8');return [path]


async def native():
    from dsh.boot import boot,reconcile_profile_patches
    result=[];raw=[]
    for mode in MODES:
        directory=OUTPUT/'files'/'native'/mode;directory.mkdir(parents=True)
        path=directory/'root.json';path.write_text('[]',encoding='utf-8')
        row=dict(id='candidate',name='cordis:broken',config=dict(revision=1))
        if mode in ('pending','required-pending'):row['name']='cordis:waiting'
        if mode in ('held','dispose-error'):row['name']='cordis:held'
        if mode.startswith('missing'):row['name']='cordis:absent'
        patches=[] if mode=='new' else [dict(insert=[row])]
        entered=asyncio.Event();release=asyncio.Event();events=[]
        def setup(ctx):
            def broken(owner,config):raise RuntimeError('candidate activation failed')
            def waiting(owner,config):pass
            waiting.inject=['missingService']
            def held(owner,config):
                async def cleanup():
                    entered.set()
                    if mode=='held':await release.wait()
                    else:raise RuntimeError('dispose failed')
                owner.effect(lambda:cleanup)
            ctx.loader.builtins.update(broken=broken,waiting=waiting,held=held)
            ctx.on('app-boot/config-reload',lambda *args:events.append(list(args)))
        warning=io.StringIO()
        with contextlib.redirect_stderr(warning):ctx=await boot('probe',str(path),patches,setup)
        try:
            before=next((r for r in ctx.loader.entries() if r.options['id']=='candidate'),None)
            fiber=before.fiber if before is not None else None
            next_patches=[] if mode in ('remove','held','dispose-error') else [dict(insert=[row])]
            if mode in ('changed','missing-changed'):next_patches.append(dict(id='candidate',config=dict(revision=2)))
            required=['candidate'] if mode in ('required','required-pending') else []
            settled_before=None
            operation=asyncio.create_task(reconcile_profile_patches(ctx,next_patches,'probe',required))
            if mode=='held':
                await asyncio.wait_for(entered.wait(),3)
                settled_before=operation.done();release.set()
            error=None;warnings=[]
            with contextlib.redirect_stderr(warning):
                try:warnings=await operation
                except Exception as failure:error=str(failure)
            after=next((r for r in ctx.loader.entries() if r.options['id']=='candidate'),None)
            result.append(dict(mode=mode,fatal=error is not None,warnings=len(warnings),same_entry=before is after,
                same_fiber=after is not None and fiber is after.fiber,removed=after is None,events=events,
                settled_before=settled_before,active=after is not None and after.fiber is not None and after.fiber.state==2,
                error_mentions_candidate=error is not None and 'candidate' in error,
                warning_kind='pending' if warnings and 'pending' in warnings[0] else 'failed' if warnings else None))
            raw.append(dict(mode=mode,error=error,warnings=warnings,log=warning.getvalue()))
        finally:
            release.set()
            with contextlib.redirect_stderr(warning):await ctx.fiber.dispose()
    (OUTPUT/'native-diagnostics.json').write_text(json.dumps(raw),encoding='utf-8')
    return result


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_reconcile.mts','Previous failure identity/config, required ids, pending warnings and removed Fiber settlement.',
        [Path(__file__).resolve(),ROOT/'dsh/boot/recomposition.py',ROOT/'reference/packages/boot/app-boot/src/index.ts'],prepare)
