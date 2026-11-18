"""Observe ordered bundle files and skipped-layer policy against fixed Source."""
import contextlib
import io
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
MODES = ('ordinary', 'grant', 'user-broken', 'bundles-only', 'retired')


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'; path.write_text(json.dumps(MODES), encoding='utf-8')
    return [path]


def fixture(directory, mode):
    app = directory/'app'; app.mkdir(parents=True)
    profile = directory/'profile'; profile.mkdir()
    (app/'package.json').write_text('{}', encoding='utf-8')
    selected = ['multi', 'missing', 'bad-paths', 'broken', 'not-bundle', 'restricted', 'bad-platforms', 'guarded', 'kept']
    for name in selected:
        if name == 'missing': continue
        package = app/'node_modules'/name; package.mkdir(parents=True)
        bundle = dict(patch='./patch.yml')
        if name == 'multi': bundle['patch'] = ['./first.yml', './layers/second.yml']
        if name == 'bad-paths': bundle['patch'] = [1]
        if name == 'restricted': bundle['platforms'] = ['darwin' if sys.platform != 'darwin' else 'win32']
        if name == 'bad-platforms': bundle['platforms'] = []
        manifest = dict(name=name, version='1.0.0', dsh=dict(bundle=bundle))
        if name == 'not-bundle': manifest.pop('dsh')
        if name == 'guarded': manifest['engines'] = dict(dsh='^99')
        (package/'package.json').write_text(json.dumps(manifest), encoding='utf-8')
        (package/'patch.yml').write_text('[' if name == 'broken' else json.dumps([dict(insert=[dict(id=name, name='cordis:group')])]), encoding='utf-8')
        if name == 'multi':
            (package/'layers').mkdir()
            (package/'first.yml').write_text(json.dumps([dict(insert=[dict(id='first',name='./local.mjs',config=dict(value=1))])]), encoding='utf-8')
            (package/'layers/second.yml').write_text(json.dumps([dict(id='first',config=dict(value=2)), dict(insert=[dict(id='second',name='./local.mjs')])]), encoding='utf-8')
    if mode == 'retired': selected += ['@deepseek-ai/dsh-experimental-schedule-bundle', '@deepseek-ai/dsh-experimental-agent-team-profile']
    (profile/'package.json').write_text(json.dumps(dict(name='profile', preserved='yes', dsh=dict(profile=dict(bundles=selected)))), encoding='utf-8')
    (profile/'cordis.patch.yml').write_text('[' if mode in ('user-broken','bundles-only') else json.dumps([dict(id='first',config=dict(value=3))]), encoding='utf-8')
    (profile/'compatibility.json').write_text(json.dumps({'guarded@1.0.0':['0.2.2-rc.3']} if mode == 'grant' else {}), encoding='utf-8')
    return app/'package.json', profile


async def native():
    from dsh.boot.profile import load_profile_directory, compose_entries, report_skipped_bundles
    from dsh.boot import plugin_compatibility as plugin
    from dsh.boot.bundle_platform import assert_bundle_platform
    current = plugin.get_dsh_runtime_version; plugin.get_dsh_runtime_version = lambda:'0.2.2-rc.3'
    result = []
    try:
        for mode in MODES:
            directory = OUTPUT/'files'/'native'/mode
            anchor, profile = fixture(directory, mode)
            before = (profile/'package.json').read_bytes(); loaded = None; error = False
            warning = io.StringIO()
            with contextlib.redirect_stderr(warning):
                try: loaded = load_profile_directory('probe', str(profile), str(anchor), dict(userLayer=mode!='bundles-only'))
                except Exception: error = True
            row = dict(mode=mode, error=error, silent=not warning.getvalue(), manifest=json.loads((profile/'package.json').read_text(encoding='utf-8')), unchanged=before==(profile/'package.json').read_bytes())
            if loaded is not None:
                rendered = io.StringIO()
                with contextlib.redirect_stderr(rendered): report_skipped_bundles('probe', loaded)
                row.update(layers=[dict(name=layer.packageName, paths=[str(Path(p).relative_to(directory)).replace('\\','/') for p in layer.patchPaths]) for layer in loaded.layers],
                    skipped=[s['packageName'] for s in loaded.skippedBundles], reasons=dict((s['packageName'], next((value for value in ('cannot resolve profile bundle', 'file path or a list', 'failed to parse', 'declares no dsh.bundle', 'Host is running', 'nonempty list', 'incompatible with dsh') if value in s['reason']), 'other')) for s in loaded.skippedBundles),
                    entries=compose_entries([*[layer.patches for layer in loaded.layers], loaded.patches]), report_lines=len(rendered.getvalue().splitlines()))
                for entry in row['entries']:
                    if entry['name'].startswith('file:'): entry['name']=entry['name'].replace(directory.as_uri(), '$ROOT')
            result.append(row)
        for platforms in (None, [], ['wsl'], ['linux'], ['win32'], ['bogus'], 'win32', ['wsl','darwin']):
            for platform in ('win32','linux','darwin'):
                for marker in (False,True):
                    try:
                        assert_bundle_platform(platforms, platform, dict(env={'WSL_INTEROP':'yes'} if marker else {}, osRelease='generic'))
                        error = None
                    except Exception as failure: error = str(failure)
                    result.append(dict(platforms=platforms,platform=platform,marker=marker,error=error))
        return result
    finally: plugin.get_dsh_runtime_version = current


if __name__ == '__main__':
    probe.native = native
    source=ROOT/'reference'
    probe.main('rc022_profile_layers.mts', 'Bundle multi-file order, skipped layers, compatibility grants, retired list removal, user errors and Host platform matrix.',
        [Path(__file__).resolve(), ROOT/'dsh/boot/profile.py', ROOT/'dsh/boot/bundle_platform.py', source/'packages/boot/app-boot/src/profile.ts', source/'packages/boot/app-boot/src/bundle-platform.ts'], prepare)
