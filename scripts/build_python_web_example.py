"""Build the plain-JS example's original-loader bundle on an author machine.

No product browser source changes, Node runtime, or target-side compilation.
This is deliberately not a general TypeScript/JSX compiler.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'examples/python-web-echo'


def write_text(path, text):
    # Keep build receipts valid after a Git checkout on either Windows or POSIX.
    with path.open('w', encoding='utf-8', newline='') as stream:
        stream.write(text)


def build(project=PROJECT):
    project = Path(project)
    manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    contract = (project / 'remote/contract.json').read_text(encoding='utf-8')
    source = (project / 'src/client.js').read_text(encoding='utf-8')
    bundle = ('window.__ModuleLoader__.load({id: ' + json.dumps(manifest['name']) + ', factory: function(require) {\n'
        'var module = {exports: {}}; var exports = module.exports;\n'
        'var React = require("react"); var CONTRACT = ' + contract.strip() + ';\n' + source + '\n'
        'return module.exports;\n}});\n//# sourceMappingURL=client.js.map\n')
    (project / 'client').mkdir(exist_ok=True)
    with (project / 'client/client.js').open('w', encoding='utf-8', newline='') as stream:
        stream.write(bundle)
    source_map = dict(version=3, sources=['../src/client.js'], sourcesContent=[source], names=[], mappings='')
    write_text(project / 'client/client.js.map', json.dumps(source_map, ensure_ascii=True) + '\n')
    paths = ('client/client.js', 'client/client.js.map', 'remote/contract.json', 'remote/typert.py')
    baseline = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))
    manifest['dsh']['webArtifacts'] = dict(formatVersion=1, targetUpstream=baseline['target_upstream'],
        files={path: hashlib.sha256((project / path).read_bytes()).hexdigest() for path in paths})
    write_text(project / 'package.json', json.dumps(manifest, ensure_ascii=True, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    print('Built ' + build()['name'])
