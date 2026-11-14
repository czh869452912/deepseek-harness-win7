"""Pair launch snapshots and fresh disk composition without Loader mutation."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_recompose_probe import fixture
OUTPUT=None
MODES=['current','initial','edited-bundle','edited-initial','invalid-canonical','invalid-user','missing-user','missing-home','invalid-home','no-telemetry','bundle-selection']


def prepare(output):
    global OUTPUT
    OUTPUT=output
    specs=[dict(mode=mode,env=env) for mode in MODES for env in (None,'','0','false')]
    path=output/'input.json';path.write_text(json.dumps(specs),encoding='utf-8');return [path]


def stage(directory,mode):
    from dsh.boot.profile import load_profile_directory
    options,_=fixture(directory);active=Path(options['profile']['dir']);home=Path(options['home'])
    bundle=active/'node_modules/selected/patch.yml'
    bundle.write_text(json.dumps([dict(insert=[dict(id='session-telemetry-otel',name='telemetry',config=dict(value='bundle'))])]),encoding='utf-8')
    canonical=active/'cordis.patch.yml';canonical.write_text(json.dumps([dict(id='session-telemetry-otel',config=dict(value='initial-user'))]),encoding='utf-8')
    initial=load_profile_directory('probe',str(active),options['installAnchor'])
    custom=active/'custom.patch.yml';custom.write_text(json.dumps([dict(id='session-telemetry-otel',config=dict(value='current-user'))]),encoding='utf-8')
    home_patch=home/'cordis.patch.yml';home_patch.write_text(json.dumps([dict(id='session-telemetry-otel',disabled=True)]),encoding='utf-8')
    if mode.startswith('edited-'):bundle.write_text(json.dumps([dict(insert=[dict(id='session-telemetry-otel',name='telemetry',config=dict(value='edited-bundle'))])]),encoding='utf-8')
    if mode=='invalid-canonical':canonical.write_text('{broken',encoding='utf-8')
    if mode=='invalid-user':custom.write_text('{broken',encoding='utf-8')
    if mode=='missing-user':custom.unlink()
    if mode=='missing-home':home_patch.unlink()
    if mode=='invalid-home':home_patch.write_text('{}',encoding='utf-8')
    if mode=='no-telemetry':bundle.write_text('[]',encoding='utf-8')
    if mode=='bundle-selection':
        manifest=active/'package.json';value=json.loads(manifest.read_text(encoding='utf-8'));value['dsh']['profile']['bundles']=[];manifest.write_text(json.dumps(value),encoding='utf-8')
    context=dict(name='active',dir=str(active),patchPath=str(custom),installAnchor=options['installAnchor'],home=str(home),cwd=str(directory),startedBundles=['selected'],overlays=[dict(id='session-telemetry-otel',disabled=False)])
    return context,initial


async def native():
    from dsh.boot.profile_context import read_profile_patches
    from dsh.boot.profile import compose_entries
    from scripts.rc022_resolution_probe import files
    specs=json.loads((OUTPUT/'input.json').read_text(encoding='utf-8'));result=[]
    for index,spec in enumerate(specs):
        context,initial=stage(OUTPUT/'files/native'/str(index),spec['mode']);context['telemetryDisabledEnv']=spec['env']
        before=files(Path(context['home']).parent)
        try:
            patches=read_profile_patches('probe',context,initial if spec['mode'] in ('initial','edited-initial') else None)
            result.append(dict(**spec,error=False,patches=patches,entries=compose_entries([patches]),unchanged=files(Path(context['home']).parent)==before))
            detached=read_profile_patches('probe',context,initial if spec['mode'] in ('initial','edited-initial') else None)
            detached[-1]['disabled']=True
            assert context['overlays'][0]['disabled'] is False
        except Exception:
            result.append(dict(**spec,error=True,unchanged=files(Path(context['home']).parent)==before))
    return result


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_profile_context.mts','Live bundle/user/home layers, initial snapshots, detached overlays and launch-time telemetry precedence.',
        [Path(__file__).resolve(),ROOT/'dsh/boot/profile_context.py'],prepare)
