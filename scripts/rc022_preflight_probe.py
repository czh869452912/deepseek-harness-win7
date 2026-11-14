"""Exercise actual profile admission and boot without evaluating denied code."""
import contextlib
import io
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
MODES = ['basic', 'exempt', 'other-version', 'other-runtime', 'relative', 'absolute', 'url', 'alias',
    'group', 'disabled-group', 'denied-group', 'include', 'include-patched', 'initial', 'cycle',
    'mapping', 'dynamic', 'missing', 'malformed', 'null', 'disabled', 'non-profile', 'no-base', 'service', 'bad-record']
BOOT_MODES = ['basic', 'exempt', 'other-version', 'other-runtime', 'group', 'include', 'malformed', 'null', 'alias']


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'; path.write_text(json.dumps(dict(modes=MODES, boot=BOOT_MODES)), encoding='utf-8')
    return [path]


def fixture(directory, mode, boot=False):
    directory.mkdir(parents=True)
    extension = 'py' if boot else 'mjs'
    for name in ('allowed', 'denied', 'malformed', 'null'):
        package = directory/'node_modules'/name; package.mkdir(parents=True)
        manifest = dict(name=name, version='2.0.0' if name == 'denied' and mode == 'other-version' else '1.0.0',
            type='module', exports='./index.'+extension)
        if name == 'denied': manifest['engines'] = {'dsh': '^99'}
        if name == 'malformed': manifest['peerDependencies'] = []
        (package/'package.json').write_text(json.dumps(None if name == 'null' else manifest), encoding='utf-8')
        effect = str(directory/'effects')
        content = ("from pathlib import Path\ndef record(value):\n    with Path("+repr(effect)+").open('a',encoding='utf-8') as f: f.write(value+'\\n')\nrecord('import:"+name+"')\ndef apply(ctx, config): record('apply:"+name+"')\n") if boot else 'throw new Error("must not import in preflight")'
        (package/('index.'+extension)).write_text(content, encoding='utf-8')
    def row(name, id=None): return dict(id=id or name, name=name)
    denied = row('denied'); allowed = row('allowed')
    rows = [allowed, denied]
    if mode in ('relative', 'absolute', 'url'):
        path = directory/'node_modules/denied'/('index.'+extension)
        rows = [dict(id='denied', name={'relative': './node_modules/denied/index.'+extension, 'absolute': str(path), 'url': path.as_uri()}[mode])]
    if mode == 'alias':
        alias = directory/'aliased'; alias.mkdir()
        for source in (directory/'node_modules/denied').iterdir():
            (alias/source.name).write_bytes(source.read_bytes())
        (directory/'package.json').write_text(json.dumps(dict(imports={'#denied': './aliased/index.'+extension})), encoding='utf-8')
        rows = [dict(id='alias', name='#denied')]
    if mode in ('group', 'disabled-group'):
        rows = [dict(id='group', name='cordis:group', group=True, config=rows)]
        if mode == 'disabled-group': rows[0]['disabled'] = True
    if mode == 'denied-group': rows = [dict(id='group', name='denied', group=True, config=[allowed])]
    if mode in ('include', 'include-patched', 'initial', 'cycle', 'mapping', 'dynamic'):
        path = directory/'nested.yml'
        config = dict(path=path.as_uri())
        if mode == 'cycle':
            (directory/'inner.yml').write_text(json.dumps([dict(id='inner', name='cordis:include', config=dict(path=path.as_uri()))]), encoding='utf-8')
            content = [dict(id='outer', name='cordis:include', config=dict(path=(directory/'inner.yml').as_uri()))]
        else: content = dict(mapping=True) if mode == 'mapping' else [denied]
        if mode == 'initial': config['initial'] = [denied]
        else: path.write_text(json.dumps(content), encoding='utf-8')
        if mode == 'include-patched': config['patches'] = [dict(id='denied', disabled=True)]
        if mode == 'dynamic': config['path'] = './dynamic.py'
        rows = [dict(id='include-denied', name='cordis:include', config=config), allowed]
    if mode == 'missing': rows = [row('./missing.mjs', 'missing'), row('node:fs', 'builtin')]
    if mode in ('malformed', 'null'): rows = [allowed, row(mode)]
    if mode == 'disabled': rows = [dict(denied, disabled=True)]
    if mode == 'service': rows = [row('virtual-plugin', 'virtual')]
    grants = {'denied@1.0.0': ['9.9.9' if mode == 'other-runtime' else '0.2.2-rc.3']} if mode in ('exempt', 'other-version', 'other-runtime', 'bad-record') else {}
    if mode == 'bad-record': grants['bad@*'] = ['0.2.2-rc.3']
    (directory/'compatibility.json').write_text(json.dumps(grants), encoding='utf-8')
    (directory/'cordis.yml').write_text('[]\n', encoding='utf-8')
    return rows


def normalize(value, directory):
    return json.loads(json.dumps(value).replace(str(directory).replace('\\', '\\\\'), '$ROOT').replace(directory.as_uri(), '$URL'))


async def native():
    from dsh.boot import boot, prepare_profile_entries, prepare_profile_patches
    from dsh.boot import plugin_compatibility as plugin
    from dsh.cordis import Context
    current = plugin.get_dsh_runtime_version; plugin.get_dsh_runtime_version = lambda: '0.2.2-rc.3'
    result = []; raw_warnings = []
    try:
        for mode in MODES:
            directory = OUTPUT/'files'/'native'/'rows'/mode
            rows = fixture(directory, mode)
            before = json.dumps(rows); files = {str(p):p.read_bytes() for p in directory.rglob('*') if p.is_file()}
            ctx = Context()
            if mode != 'non-profile': ctx.provide('profileContext', dict(dir=str(directory)))
            if mode == 'service':
                class Packages:
                    def packageOf(self, specifier, base):
                        return dict(manifestPath=str(directory/'node_modules/denied/package.json'))
                ctx.provide('pluginPackages', Packages())
            warning = io.StringIO(); error = None; output = None
            try:
                with contextlib.redirect_stderr(warning):
                    try: output = prepare_profile_entries(ctx, rows, None if mode == 'no-base' else directory.as_uri()+'/')
                    except ValueError as failure: error = str(failure)
                patches = [dict(insert=rows)]
                if mode == 'non-profile': assert prepare_profile_patches(ctx, patches, directory.as_uri()+'/') is patches
                result.append(dict(mode=mode, rows=normalize(output, directory), error=error,
                    unchanged=before==json.dumps(rows) and all(Path(p).read_bytes()==data for p,data in files.items()),
                    imported=(directory/'effects').exists(),
                    diagnostics=dict(denials=warning.getvalue().count('disabling profile plugin'),
                        invalid='cannot be validated' in warning.getvalue(), include='never rewritten' in warning.getvalue(), record='record is ignored' in warning.getvalue())))
                raw_warnings.append(dict(mode=mode, warning=warning.getvalue()))
            finally: await ctx.fiber.dispose()
        for mode in BOOT_MODES:
            directory = OUTPUT/'files'/'native'/'boot'/mode
            rows = fixture(directory, mode, True); before = {str(p):p.read_bytes() for p in directory.rglob('*') if p.is_file()}
            warning = io.StringIO()
            def setup(ctx): ctx.provide('profileContext', dict(dir=str(directory)))
            with contextlib.redirect_stderr(warning):
                ctx = await boot('probe', str(directory/'cordis.yml'), [dict(insert=rows)], setup)
            try:
                effects = (directory/'effects').read_text(encoding='utf-8').splitlines() if (directory/'effects').exists() else []
                result.append(dict(boot=mode, effects={name:[value for value in effects if value.endswith(':'+name)] for name in ('allowed', 'denied')},
                    unchanged=all(Path(p).read_bytes()==data for p,data in before.items()), denials=warning.getvalue().count('disabling profile plugin')))
                raw_warnings.append(dict(boot=mode, warning=warning.getvalue(), effects=effects))
            finally: await ctx.fiber.dispose()
        (OUTPUT/'native-warnings.json').write_text(json.dumps(raw_warnings), encoding='utf-8')
        return result
    finally: plugin.get_dsh_runtime_version = current


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_preflight.mts', 'Detached profile admission rows and actual boot import effects, nested Include refusal without file edits.',
        [Path(__file__).resolve(), ROOT/'dsh/boot/compatibility_preflight.py', ROOT/'dsh/boot/app_boot.py',
         ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/boot/app-boot/src/compatibility-preflight.ts'], prepare, node_args=('--expose-internals',))
