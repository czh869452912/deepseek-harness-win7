"""Package an exported plain-JS body using the original browser evaluator."""
import hashlib
import json
import os
import shutil
import tempfile

from dsh.boot.python_package import inside, package_name, validate_sources
from dsh.boot.python_plugins import atomic_bytes, MAX_FILES, MAX_BYTES, reparse
from dsh.extensions.packaged_host import host_remote_namespace


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, indent=2) + '\n').encode('utf-8')


def build_exported_client(project):
    project = os.path.abspath(project)
    if reparse(project):
        raise ValueError('build project must not be a link or junction')
    with open(os.path.join(project, 'package.json'), encoding='utf-8') as stream:
        manifest = json.load(stream)
    name = package_name(manifest['name'])
    descriptor = manifest.get('dsh', {}).get('sourceExport')
    if not isinstance(descriptor, dict):
        raise ValueError('build requires an exported Python source project')
    with open(inside(project, descriptor['record']), encoding='utf-8') as stream:
        origin = json.load(stream)
    if origin.get('formatVersion') != 1 or 'client' not in origin.get('sourceSha256', {}):
        raise ValueError('build requires an exported Client source record')
    if origin.get('placement') != 'host':
        raise ValueError('Client source build currently requires Host placement; session Remote ownership is not implemented')
    if manifest['dsh']['python']['entry'] != 'exported.plugin:plugin' or manifest['dsh']['python']['sourceRoot'] != 'python':
        raise ValueError('build requires the exported Python SDK entry')
    source_path = inside(project, 'client/source.js')
    with open(source_path, encoding='utf-8', newline='') as stream:
        source = stream.read()
    if not source.strip():
        raise ValueError('exported Client source must not be empty')
    runtime_root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(runtime_root, 'extensions', 'inspect_catalog.json'), encoding='utf-8') as stream:
        target = json.load(stream)['target_upstream']
    namespace = host_remote_namespace(name)
    contract = dict(package=name, face='host', schemas=[], model=dict(services=[], events=[], objects=[]),
        invocations=[dict(id=name + '#' + namespace + '.call', service=namespace, namespace=namespace,
            method='call', invocation=dict(kind='direct'), parameters=[
                dict(name='method', wire='method', source='json', codec=dict(mode='strict', typeSymbol=name + '#Method', schema=dict(type='string'))),
                dict(name='args', wire='args', source='json', codec=dict(mode='strict', typeSymbol=name + '#JsonValue', schema={}))],
            result=dict(mode='strict', typeSymbol=name + '#JsonValue', schema={}))])
    with open(os.path.join(runtime_root, 'extensions', 'packaged_client.js'), encoding='utf-8', newline='') as stream:
        adapter = stream.read()
    identity = dict(pluginId='python-export-' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:24],
        packageId=origin['packageId'], pluginRunId=manifest['version'], name=name)
    bundle = ('window.__ModuleLoader__.load({id: ' + json.dumps(name) + ', factory: function(require) {\n'
        'var module = {exports: {}}; var exports = module.exports;\n'
        'var SDK = require("@deepseek-ai/dsh-cordis-client-runner");\n'
        'var CLIENT_SOURCE = ' + json.dumps(source, ensure_ascii=True) + ';\n'
        'var CONTRACT = ' + json.dumps(contract, ensure_ascii=True) + ';\n'
        'var IDENTITY = ' + json.dumps(identity, ensure_ascii=True) + ';\n' + adapter + '\n'
        'return module.exports;\n}});\n//# sourceMappingURL=client.js.map\n')
    has_host = os.path.isfile(inside(project, 'python/exported/host.body.py'))
    entry = ('import os\nfrom dsh.plugin_api import python_host_source\n\n'
        'plugin = python_host_source(' + ('os.path.join(os.path.dirname(__file__), "host.body.py")' if has_host else 'None') + ', ' + repr(name) + ', enable_remote=True)\n')
    artifact = ('import json\nimport os\nfrom dsh.plugin_api import JsonSchemaCodec\n\n'
        'with open(os.path.join(os.path.dirname(__file__), "contract.json"), encoding="utf-8") as stream:\n'
        '    TYPERT = json.load(stream)\n'
        'for invocation in TYPERT["invocations"]:\n'
        '    for field in invocation["parameters"] + [dict(codec=invocation["result"])]:\n'
        '        field["codec"]["schema"] = JsonSchemaCodec(field["codec"]["schema"])\n')
    files = {'client/client.js': bundle.encode('utf-8'), 'client/client.js.map': encoded(dict(version=3,
        sources=['source.js'], sourcesContent=[source], names=[], mappings='')),
        'remote/contract.json': encoded(contract), 'remote/typert.py': artifact.encode('utf-8'),
        'python/exported/plugin.py': entry.encode('utf-8')}
    receipt_paths = list(files) + ['client/source.js'] + (['python/exported/host.body.py'] if has_host else [])
    hashes = {}
    for relative in receipt_paths:
        if relative in files:
            hashes[relative] = hashlib.sha256(files[relative]).hexdigest()
        else:
            with open(inside(project, relative), 'rb') as stream:
                hashes[relative] = hashlib.sha256(stream.read()).hexdigest()
    manifest['exports'] = {'./client': './client/client.js', './typert': './remote/typert.py'}
    manifest['dsh']['client'] = dict(platform='web', inject=['@deepseek-ai/dsh-cordis-client-runner'])
    manifest['dsh']['webArtifacts'] = dict(formatVersion=1, targetUpstream=target, files=hashes)
    descriptor['files'] += [path for path in files if path not in descriptor['files']]
    origin['requiresClientBuild'] = False
    origin['clientBuild'] = dict(formatVersion=1, targetUpstream=target,
        sourceSha256=hashes['client/source.js'], evaluator='@deepseek-ai/dsh-cordis-client-runner')
    files[descriptor['record']] = encoded(origin)
    files['package.json'] = encoded(manifest)
    # Validate a complete candidate before changing an author's existing build.
    # Copy only the declared source set, never local credentials or a venv.
    with tempfile.TemporaryDirectory(prefix='dsh-client-build-') as candidate:
        total = 0
        if len(descriptor['files']) > MAX_FILES:
            raise ValueError('build source exceeds file limit')
        for relative in descriptor['files']:
            body = files.get(relative)
            if body is None:
                original = inside(project, relative)
                current = project
                for part in relative.split('/'):
                    current = os.path.join(current, part)
                    if reparse(current):
                        raise ValueError('build source must not contain links')
                if not os.path.isfile(original):
                    raise ValueError('build source file is missing: ' + relative)
                total += os.path.getsize(original)
                if total > MAX_BYTES:
                    raise ValueError('build source exceeds byte limit')
                destination = inside(candidate, relative)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copyfile(original, destination)
            else:
                total += len(body)
                destination = inside(candidate, relative)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                atomic_bytes(destination, body)
        from dsh.boot.python_plugin_export import release_files
        release_files(candidate)
        for relative in receipt_paths:
            if relative not in files:
                with open(inside(project, relative), 'rb') as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != hashes[relative]:
                        raise ValueError('source changed during Client build: ' + relative)
    # Descriptor publication is last; raw exports cannot be installed in between.
    for relative, body in files.items():
        destination = inside(project, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        atomic_bytes(destination, body)
    validate_sources(project)
    return name
