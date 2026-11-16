"""Exact-version management over actual profile Include/Loader/HMR trees."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


def corpus():
    return ['live', 'startup', 'reload-failure', 'damaged', 'range', 'whitespace',
            'credential', 'runtime-range', 'scoped', 'old-runtime', 'alias', 'boolean-risk']


async def observe(workspace=None):
    import dsh
    from dsh.boot.app_boot import boot
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.boot.profile_context import read_profile_patches
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.timer import TimerService
    output = []
    previous = dsh.__version__
    dsh.__version__ = '0.2.2-rc.3'
    try:
        for mode in corpus():
            home = (workspace or WORKSPACE)/'native'/mode
            directory = home/'profile'
            def write(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding='utf-8')
            write(home/'package.json', dict(name='installation'))
            write(directory/'package.json', dict(name='profile', dsh=dict(profile=dict(bundles=['core', 'extra']))))
            for name, rows in [('core', [dict(id='manager', name='cordis:manager')]),
                               ('extra', [dict(id='managed', name='cordis:active')])]:
                package = directory/'node_modules'/name
                manifest = dict(name=name, version='1.0.0', dsh=dict(bundle=dict(patch='patch.yml')))
                if name == 'extra':manifest['engines'] = dict(dsh='>=99.0.0')
                write(package/'package.json', manifest)
                write(package/'patch.yml', [dict(insert=rows)])
            write(directory/'cordis.yml', [])
            write(directory/'cordis.patch.yml', [])
            profile = dict(name='test', dir=str(directory), patchPath=str(directory/'cordis.patch.yml'),
                installAnchor=str(home/'package.json'), cwd=str(home), home=str(home), startedBundles=['core', 'extra'], overlays=[])
            def setup(ctx):
                ctx.provide('profileContext', profile)
                ctx.provide('appReady', NS(onReady=lambda listener:(listener(), lambda:None)[1]))
                ctx.loader.builtins.update(manager=CurrentPluginManager, active=lambda owner, config:owner.provide('exemptionProbe', True))
            ctx = await boot('test', str(directory/'cordis.yml'), read_profile_patches('test', profile), setup)
            facts = []
            ctx.on('plugin-manager/operation', lambda event:facts.append(event))
            try:
                if mode != 'startup':
                    await ctx.plugin(TimerService)
                    await ctx.plugin(ConfigWatcherService, dict(root=[], ignored=[], debounce=0))
                    await ctx.hmr.runExclusive(lambda:None)
                if mode == 'reload-failure':
                    async def failed(required):raise RuntimeError('reload failed')
                    ctx.hmr.reconcileProfile = failed
                if mode == 'damaged':(directory/'compatibility.json').write_text('[invalid', encoding='utf-8')
                runtime = dsh.__version__
                actions = [('extra@1.0.0', runtime, True, None), ('extra@1.0.0', runtime, True, True),
                           ('extra@1.0.0', runtime, True, True), ('extra@1.0.0', runtime, False, None)]
                variants = dict(range=('extra@^1.0.0', runtime), whitespace=(' extra@1.0.0 ', runtime),
                    credential=('https://user:secret@example.com/pkg', runtime),
                    **{'runtime-range':('extra@1.0.0', '^1.0.0'), 'scoped':('@scope/extra@2.0.0', runtime),
                       'old-runtime':('extra@1.0.0', '0.0.1'), 'alias':('npm:extra@1.0.0', runtime)})
                if mode in variants:
                    package, requested_runtime = variants[mode]
                    actions = [(package, requested_runtime, True, True), (package, requested_runtime, False, None)]
                if mode == 'boolean-risk':actions = [('extra@1.0.0', runtime, True, 1)]
                steps = []
                for package, requested_runtime, enabled, risk in actions:
                    result = await ctx.pluginManager.setVersionExemption(package, requested_runtime, enabled, risk)
                    for _ in range(15):await asyncio.sleep(0)
                    if 'error' in result and 'diagnostic' in result['error']:result['error']['diagnostic'] = True
                    listing = ctx.pluginManager.listVersionExemptions()
                    listing['warnings'] = len(listing['warnings'])
                    steps.append(dict(result=result, listing=listing, active=ctx.get('exemptionProbe') is True,
                                      selection=json.loads((directory/'package.json').read_text(encoding='utf-8'))['dsh']['profile']['bundles']))
                facts = [{key:value for key,value in fact.items() if key not in ('id', 'time')} for fact in facts]
                output.append(dict(name=mode, steps=steps, facts=facts))
            finally:await ctx.fiber.dispose()
        return output
    finally:dsh.__version__ = previous


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files'
    WORKSPACE.mkdir()
    path = output/'input.json'
    path.write_text(json.dumps(dict(workspace=str(WORKSPACE), cases=corpus())), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_manager_exemptions.mts', 'Exact-version exemptions through real Include/Loader/HMR trees; risk acknowledgement, runtime and package validation, live admission/revocation, startup restart, persistence before reload failure, corrupted files, idempotence, independent scoped identity and credential-private diagnostic facts. Compare diagnostic presence and warning count only.',
        [Path(__file__).resolve(), ROOT/'dsh/boot/plugin_manager_current.py', ROOT/'dsh/boot/profile_compatibility.py'], prepare=prepare)
