"""Pair actual imports and compatibility admission through package resources."""
import contextlib
import io
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_resolution_probe import package
OUTPUT = None
CASES = [
    dict(exports={'.': {'node': './node.ENTRY', 'default': './root.ENTRY'}}, requests=['lib']),
    dict(exports={'./*': './wild/*.ENTRY', './feature/*': './specific/*.ENTRY'}, requests=['lib/feature/item', 'lib/other']),
    dict(exports={'.': ['not-relative', './root.ENTRY']}, requests=['lib']),
    dict(exports={'.': ['./missing.ENTRY', './root.ENTRY']}, requests=['lib']),
    dict(exports={'.': None}, requests=['lib', 'lib/root.ENTRY']),
    dict(exports={'.': '../outside.ENTRY'}, requests=['lib']),
    dict(exports=None, requests=['lib/root.ENTRY', 'lib/root']),
    dict(exports={'.': './root.ENTRY', './feature': './node.ENTRY'}, self=True, requests=['lib', 'lib/feature']),
    dict(exports={'.': './root.ENTRY'}, imports={'#data': 'lib'}, requests=['#data']),
    dict(exports={'.': './root.ENTRY'}, imports={'#data/*': './specific/*.ENTRY'}, requests=['#data/item']),
    dict(exports={'.': './root.ENTRY'}, imports={'#data': {'node': './node.ENTRY', 'default': './root.ENTRY'}}, requests=['#data']),
    dict(exports={'.': './root.ENTRY'}, imports={'#data': None}, requests=['#data']),
    dict(exports={'.': './root.ENTRY'}, imports={'#data': '../outside.ENTRY'}, requests=['#data']),
    dict(exports={'.': './root.ENTRY'}, imports={'#data': 'lib'}, denied=True, requests=['#data', 'lib']),
    dict(exports={'.': './root.ENTRY'}, self=True, denied=True, requests=['lib']),
    dict(exports={'.': './root.ENTRY'}, requests=['./root.ENTRY', './folder/'])]


def prepare(output):
    global OUTPUT
    OUTPUT = output
    cases = []
    for index, case in enumerate(CASES):
        row = dict(index=index)
        for host, extension in [('source', 'mjs'), ('native', 'py')]:
            case = json.loads(json.dumps(CASES[index]).replace('ENTRY', extension))
            directory = output/'files'/host/str(index)
            active = directory/'profiles/active'
            anchor = package(directory/'installation', 'installation')
            library = anchor.parent/'node_modules/lib'
            fields = dict(exports=case['exports'])
            if case.get('denied'): fields['engines'] = {'dsh': '^99'}
            package(library, 'lib', **fields)
            package(active, 'lib' if case.get('self') else 'caller', **dict(fields if case.get('self') else {}, imports=case.get('imports', {})))
            for root in (active, library):
                for name in ('root', 'node', 'wild/other', 'specific/item'):
                    path = root/(name+'.'+extension); path.parent.mkdir(parents=True, exist_ok=True)
                    value = root.name+'/'+name
                    text = 'export const value='+json.dumps(value) if host == 'source' else 'value='+repr(value)+'\ndef apply(ctx, config): pass\n'
                    path.write_text(text, encoding='utf-8')
                (root/'folder').mkdir()
            parent = (active/'caller.mjs').as_uri()
            if host == 'source': (active/'caller.mjs').write_text('export function load(name) { return import(name) }', encoding='utf-8')
            table = dict(profilesDir=str(directory/'profiles'),profileDir=str(active),entries=[dict(name='lib',packageDir=str(library),declarer=str(anchor),version='1.0.0',scope='installation')],localPackageNames=[],linkedRoots=[])
            row[host] = dict(table=table,parent=parent,requests=case['requests'])
        cases.append(row)
    path = output/'input.json'; path.write_text(json.dumps(cases),encoding='utf-8'); return [path]


async def native():
    from dsh.boot import PluginPackages, prepare_profile_entries
    from dsh.boot.plugin_packages import _parent
    from dsh.cordis import Context
    from dsh.cordis.loader import Loader
    result = []; raw = []
    for case in json.loads((OUTPUT/'input.json').read_text(encoding='utf-8')):
        data = case['native']; ctx = Context(); active = Path(data['table']['profileDir'])
        ctx.baseUrl = active.as_uri()+'/'
        loader = Loader(ctx); PluginPackages(ctx, dict(resolution=data['table']))
        ctx.provide('profileContext', dict(dir=str(active)))
        try:
            for index, request in enumerate(data['requests']):
                warning = io.StringIO(); value = None; code = None
                with contextlib.redirect_stderr(warning):
                    admitted = prepare_profile_entries(ctx, [dict(id='entry',name=request)], data['parent'])
                try: value = loader.import_plugin(request).value
                except Exception as error: code = getattr(error,'code',type(error).__name__)
                result.append(dict(case=case['index'],request=index,value=value,code=code,disabled=admitted[0].get('disabled',False)))
                raw.append(dict(case=case['index'],request=request,warning=warning.getvalue()))
        finally: await ctx.fiber.dispose()
    (OUTPUT/'native-diagnostics.json').write_text(json.dumps(raw),encoding='utf-8')
    return result


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_resource_consumers.mjs', 'Actual ESM/Python imports and preflight rows for exported modules, self references and imports aliases.',
        [Path(__file__).resolve(),ROOT/'dsh/cordis/loader.py',ROOT/'dsh/boot/compatibility_preflight.py',ROOT/'dsh/boot/package_resolution.py',source/'packages/boot/app-boot/lib/index.js'],prepare,node_args=('--expose-internals',),plain_node=True)
