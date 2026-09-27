"""Inventory pinned Cordis sources and explicit official test declarations.

This is a coverage denominator, not a claim that matching Python titles prove parity.
Dynamic/parameterized declarations remain explicit review items.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('cordis', 'cosmokit', 'loader', 'include', 'hmr', 'timer', 'schemastery')

def inventory():
    tracked = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'ls-files'], encoding='utf-8').splitlines()
    python_cases = []
    for path in sorted((ROOT / 'tests').rglob('test_*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                python_cases.append((path.relative_to(ROOT).as_posix() + '::' + node.name, ast.get_docstring(node) or ''))
    files, cases = [], []
    for name in tracked:
        path = ROOT / 'reference' / name
        if not path.is_file():
            continue
        is_source = any(name.startswith('vendor/' + package + '/') for package in PACKAGES)
        is_test = name.endswith(('.spec.ts', '.spec.tsx', '.test.ts'))
        if not (is_source or is_test):
            continue
        text = path.read_text(encoding='utf-8')
        if is_test and not (is_source or re.search(r"(?:vendor/(?:cordis|loader|hmr|include|timer|schemastery)|@deepseek-ai/(?:cordis|schemastery))", text)):
            continue
        declarations = list(re.finditer(r"\b(?:it|test)(?:\.(?:skip|only|todo|concurrent))?\(\s*(['\"])((?:\\.|(?!\1)[^\\])*)\1", text)) if is_test else []
        critical = ('packages/extensions/tool-cordis/tests/cordis-lifecycle.spec.ts',
                    'packages/boot/app-boot/tests/hmr-config.spec.ts',
                    'apps/cli/tests/profile-hmr.spec.ts',
                    'packages/preset/agent-presets/tests/mount.spec.ts',
                    'packages/preset/agent-presets/tests/invariant.spec.ts')
        layer = 'foundation' if is_source else ('core-lifecycle' if name == critical[0] else
                'necessary-consumer' if name in critical else 'business-consumer')
        files.append({'path':'reference/' + name, 'layer':layer, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'kind':'official-consumer-test' if is_test else 'vendored-source',
                      'literal_cases':len(declarations),
                      'dynamic_declarations':bool(re.search(r"\b(?:it|test)\.(?:each|for)\b", text))})
        for match in declarations:
            title = re.sub(r'\\([\\\"\'])', r'\1', match.group(2))
            cases.append({'source':'reference/' + name, 'layer':layer, 'line':text.count('\n',0,match.start()) + 1,
                          'title':title, 'python_title_candidates':[case for case, doc in python_cases if title in doc],
                          'status':'requires-semantic-review'})
    return {'target_upstream':subprocess.check_output(['git','-C',str(ROOT/'reference'),'rev-parse','HEAD'],encoding='utf-8').strip(),
            'scope':'Vendored foundations and official tests with direct Cordis imports; indirect consumers require dependency traversal.',
            'files':files,'cases':cases,
            'limitations':['Literal test declarations are discovery only; parameter expansions and indirect imports are not inferred.',
                           'Python title matches identify review candidates, not completed parity.']}

if __name__ == '__main__':
    output = ROOT / 'migration/cordis-inventory.json'
    value = inventory()
    output.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print('%d files; %d literal official cases; %d title candidates' %
          (len(value['files']),len(value['cases']),sum(bool(c['python_title_candidates']) for c in value['cases'])))
