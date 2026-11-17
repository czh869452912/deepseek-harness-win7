import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.boot.market_repository_022 import repository_of, manifest_repository
from dsh.boot.market_index_022 import observe_market_operations, RESOURCE_ROOT
from scripts.rc022_market_repository_probe import cases


def test_pure_repository_and_directory_corpus():
    rows = observe_market_operations(cases())
    assert len(rows) == 822
    assert all(row['ok'] for row in rows)
    assert rows[0]['value'] == dict(host='github.com', project='o/r', url='https://github.com/o/r.git')
    assert rows[4]['value'] is None
    assert rows[-1]['value'] is None


def test_public_identity_results_do_not_leak_cached_mutation():
    first = repository_of('github:o/r'); first['project'] = 'changed'
    assert repository_of('github:o/r')['project'] == 'o/r'
    assert manifest_repository(dict(url='github:o/r', directory='../x'))['directory'] == ''
    assert manifest_repository(dict(url='github:o/r', directory='./packages/a/'))['directory'] == 'packages/a'


def test_original_dependency_and_source_projection_provenance():
    manifest = json.loads((RESOURCE_ROOT/'manifest.json').read_text(encoding='utf-8'))
    assert 'Unchanged repositoryOf' in manifest['repository_projection']
    assert 'hosted-git-info-LICENSE' in manifest['resources']
    assert 'lru-cache-LICENSE.md' in manifest['resources']
    assert any('hosted-git-info@9.0.3/' in path for path in manifest['build_inputs'])
    assert any('lru-cache@11.5.1/' in path for path in manifest['build_inputs'])
    assert any(path.endswith('packages/boot/plugin-market/src/detail.ts') for path in manifest['build_inputs'])


def test_x86_repository_projection_matches_x64():
    executable = os.environ.get('DSH_TEST_X86_PYTHON')
    if not executable: pytest.skip('explicit x86 Python fixture not configured')
    script = ('import ctypes,json,sys,os;sys.path.insert(0,os.getcwd());'
        'from dsh.boot.market_index_022 import observe_market_operations;'
        'from scripts.rc022_market_repository_probe import cases;'
        'assert ctypes.sizeof(ctypes.c_void_p)==4;'
        'print(json.dumps(observe_market_operations(cases()),ensure_ascii=True))')
    result = subprocess.run([executable, '-c', script], cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')[-2000:]
    assert json.loads(result.stdout) == observe_market_operations(cases())
