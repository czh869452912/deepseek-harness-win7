"""Regenerate pinned module ownership/dependencies and official source-test discovery.

Discovery is not certification. Dynamic declarations and dynamic service names retain
source locations for review instead of being counted as expanded test cases.
"""
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def classification(path):
    if '/tests/fixtures/' in path:
        return 'fixture', 'Upstream test fixture; never a shipped plugin.'
    if path.startswith('reference/packages/examples/'):
        return 'example', 'Example composition; validate when a downstream example is selected.'
    if (path.startswith('reference/native/') or '/sandbox-windows-acl/' in path
            or '/win32-process/' in path):
        return 'platform', 'OS-specific implementation; Python 3.8 / Win7 adapter owns compatibility.'
    if (path.startswith(('reference/packages/client/', 'reference/apps/web/', 'reference/website/'))
            or '/client-ui-' in path or '/ui-cordis/' in path or '/cordis-client-runner/' in path):
        return 'frontend', 'Browser/UI or documentation frontend; owner is the nearest package.'
    if (path == 'reference/package.json' or '/packages/test-support/' in path
            or '/typert/generator/' in path or '/webworker-packer/' in path):
        return 'tooling', 'Build, test, or workspace tooling; not a product runtime service.'
    return 'runtime', 'Host runtime, interface, SDK, or composition package; owner is the nearest package.'


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def inventory():
    modules = json.loads((ROOT / 'migration/modules.json').read_text(encoding='utf-8'))
    target = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    if target != modules['target_upstream']:
        raise RuntimeError('Reference moved; establish the new target before discovery.')
    tracked = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'ls-files'], encoding='utf-8').splitlines()
    manifests = {'reference/' + name for name in tracked if name.endswith('package.json')}
    if manifests != {row['path'] for row in modules['manifests']}:
        raise RuntimeError('Manifest set drift; update the baseline inventory first.')
    names = {row['name'] for row in modules['manifests'] if row.get('name')}
    owners = sorted((row['path'][:-len('/package.json')] for row in modules['manifests']), key=len, reverse=True)
    for row in modules['manifests']:
        path = ROOT / row['path']
        text = path.read_text(encoding='utf-8')
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != row['sha256']:
            raise RuntimeError('Manifest content drift: ' + row['path'])
        manifest = json.loads(text)
        row['classification'], row['responsibility'] = classification(row['path'])
        row['owner'] = row['path'][:-len('/package.json')]
        row['workspace_dependencies'] = [
            {'name': name, 'kind': kind, 'version': version}
            for kind in ('dependencies', 'peerDependencies', 'optionalDependencies', 'devDependencies')
            for name, version in sorted(manifest.get(kind, {}).items()) if name in names]
        row['parity'] = 'not-certified-by-inventory'
    surface_owners = {'scripts': 'tooling', 'snapshots': 'golden-reference', 'patches': 'dependency-adaptation',
                     'docs': 'documentation', 'native': 'platform', 'python': 'sdk-runtime',
                     'pnpm-lock.yaml': 'dependency-lock', 'pnpm-workspace.yaml': 'workspace-layout'}
    for row in modules['non_package_surfaces']:
        row.update(status='classified', owner=surface_owners[Path(row['path']).name],
                   parity='not-certified-by-inventory',
                   policy='Track source changes independently of manifests; select an owning task and contract before migration.')
    test_files, cases, contracts = [], [], []
    literal = re.compile(r"\b(?:it|test)(?:\.(?:skip|only|todo|concurrent))?\(\s*(['\"])((?:\\.|(?!\1)[^\\])*)\1")
    dynamic = re.compile(r'\b(?:it|test)\.(?:each|for)\b')
    hooks = re.compile(r'\b(?:inject|provide)\s*[:=(]|\b(?:ctx|context|this\.ctx)\s*\.\s*(?:get|set|provide|on|emit|serial|parallel|waterfall)\s*\(')
    for name in tracked:
        path = ROOT / 'reference' / name
        if not path.is_file() or not name.endswith(('.ts', '.tsx', '.mts', '.js', '.py')):
            continue
        source = 'reference/' + name
        text = path.read_text(encoding='utf-8')
        owner = next((parent for parent in owners if source.startswith(parent + '/')), 'reference')
        is_test = bool(re.search(r'\.(?:spec|test|e2e)\.[cm]?[jt]sx?$', name) or Path(name).name.startswith('test_')
                       or ('/tests/' in name and (literal.search(text) or dynamic.search(text))))
        if is_test:
            declarations = list(literal.finditer(text))
            test_files.append({'path': source, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'owner': owner,
                               'literal_declarations': len(declarations),
                               'parameterized_declaration_lines': [text.count('\n', 0, m.start()) + 1 for m in dynamic.finditer(text)]})
            for match in declarations:
                cases.append({'source': source, 'line': text.count('\n', 0, match.start()) + 1,
                              'title': match.group(2), 'owner': owner})
        elif '/src/' in name:
            for number, line in enumerate(text.splitlines(), 1):
                if hooks.search(line):
                    contracts.append({'source': source, 'line': number, 'owner': owner, 'expression': line.strip(),
                                      'status': 'source-discovery-not-runtime-resolution'})
    write(ROOT / 'migration/modules.json', modules)
    write(ROOT / 'migration/upstream-test-inventory.json', {
        'target_upstream': target, 'files': test_files, 'cases': cases,
        'limits': ['Literal declarations are source identities, not expanded executions or parity claims.',
                   'Parameterized factories remain located in source; selected critical expansions are in cordis-consumer-audit.json.']})
    write(ROOT / 'migration/dynamic-contract-inventory.json', {
        'target_upstream': target, 'sites': contracts,
        'limits': ['Textual discovery includes interfaces, examples and comments; service names computed at runtime remain unresolved.',
                   'The nearest package owns triage; resolving a contract allows provider and consumers to change together.']})
    return {'manifests': len(manifests), 'classifications': dict(Counter(row['classification'] for row in modules['manifests'])),
            'test_files': len(test_files), 'literal_declarations': len(cases), 'dynamic_contract_sites': len(contracts)}


if __name__ == '__main__':
    print(json.dumps(inventory(), sort_keys=True))
