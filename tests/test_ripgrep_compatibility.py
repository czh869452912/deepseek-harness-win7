"""Exact licensed native input and real search consumers; no Win7 certification."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import build_portable as build
from scripts.ripgrep_runtime_gate import validate_runtime, REQUIRED_MODULES, RUNTIME_DAMAGES


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / 'dsh/fs/tool_fs_search/bin'
DAMAGES = ('binary', 'license', 'missing-license', 'manifest', 'override', 'hardlink')
CASES = (
    ('glob', {'pattern': '*.py'}),
    ('glob', {'pattern': '*.py', 'path': 'src'}),
    ('glob', {'pattern': '*'}),
    ('glob', {'pattern': '*.missing'}),
    # Parallel multi-file grep has no stable Source order (raw counterproof is
    # retained). Compare full ordered results for controlled single-file calls.
    ('grep', {'pattern': '中文', 'path': 'src/main.py'}),
    ('grep', {'pattern': 'hello', 'include': '*.{py,md}', 'path': 'src/main.py'}),
    ('grep', {'pattern': '^hello$', 'path': 'src/main.py'}),
    ('grep', {'pattern': 'not-found', 'path': 'src/main.py'}),
    ('grep', {'pattern': '(invalid', 'path': 'src/main.py'}),
)


def test_native_input_keeps_official_identity_and_licenses():
    source, metadata = build.verify_pinned_ripgrep(ROOT)
    assert Path(source) == BIN / 'rg.exe'
    assert metadata['name'] == 'BurntSushi/ripgrep' and metadata['version'] == '14.1.0'
    assert metadata['compatibility']['directWin8SynchronizationImports'] == []
    assert metadata['compatibility']['win7Execution'] == 'deferred; not certified'
    assert metadata['archive']['sha256'] == 'fe4f75edfaa50f0d4fecbf47696b7629f3449c9c2c5a4da828753139e5a2e203'


@pytest.mark.parametrize('damage', DAMAGES)
def test_invalid_native_input_cannot_replace_previous_distribution(tmp_path, monkeypatch, damage):
    root = tmp_path / 'fixture'
    target = root / 'dsh/fs/tool_fs_search/bin'
    shutil.copytree(BIN, target)
    dist = tmp_path / 'release/dsh-win7-portable'
    dist.mkdir(parents=True)
    sentinel = dist / 'sentinel'
    sentinel.write_bytes(b'previous accepted distribution')
    archive = dist.with_name('dsh-win7-portable-v0.1.0.zip')
    archive.write_bytes(b'previous accepted ZIP')
    override = None
    if damage == 'binary':
        (target / 'rg.exe').write_bytes(b'unknown native binary')
    elif damage == 'license':
        (target / 'LICENSE-MIT').write_bytes(b'altered license')
    elif damage == 'missing-license':
        (target / 'UNLICENSE').unlink()
    elif damage == 'manifest':
        metadata = json.loads((target / 'ripgrep-input.json').read_text(encoding='utf-8'))
        metadata['compatibility']['win7Execution'] = 'certified'
        (target / 'ripgrep-input.json').write_text(json.dumps(metadata), encoding='utf-8')
    elif damage == 'override':
        override = tmp_path / 'unapproved-rg.exe'
        override.write_bytes(b'rg15 or other unapproved input')
    elif damage == 'hardlink':
        os.link(str(target / 'rg.exe'), str(tmp_path / 'shared-binary'))
    monkeypatch.setattr(build, 'ROOT_DIR', str(root))
    with pytest.raises((ValueError, FileNotFoundError)):
        build.build_portable(ripgrep_source=str(override) if override else None,
                             output_dir=str(dist.parent))
    assert sentinel.read_bytes() == b'previous accepted distribution'
    assert archive.read_bytes() == b'previous accepted ZIP'


@pytest.mark.skipif(os.name != 'nt', reason='Pinned native input is Windows x64')
def test_fresh_search_process_runs_without_host_ripgrep_or_node(tmp_path):
    (tmp_path / '中文.py').write_bytes('hello 中文\n'.encode('utf-8'))
    program = """
import asyncio, json, sys
sys.path.insert(0, sys.argv[1])
from dsh.fs.tool_fs_search.search_core import resolve_rg_path
import subprocess
binary = asyncio.run(resolve_rg_path())
completed = subprocess.run([binary, '--no-config', '--json', '--regexp=中文', '.'],
                           capture_output=True, timeout=15)
assert completed.returncode == 0, completed.stderr
rows = [json.loads(line) for line in completed.stdout.decode('utf-8').splitlines()]
matches = [row['data'] for row in rows if row['type'] == 'match']
print(json.dumps(dict(binary=binary, matches=matches)))
assert len(matches) == 1 and matches[0]['lines']['text'] == 'hello 中文\\n'
"""
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in ('PATH', 'DSH_RG_PATH', 'PYTHONPATH', 'PYTHONHOME')}
    environment['PATH'] = ''
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(ROOT)],
                            cwd=str(tmp_path), env=environment, capture_output=True, timeout=30)
    (tmp_path / 'process.stdout').write_bytes(result.stdout)
    (tmp_path / 'process.stderr').write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)['binary']) == BIN / 'rg.exe'


@pytest.mark.skipif(os.name != 'nt', reason='Compare actual Windows x64 search executables')
@pytest.mark.parametrize('case', range(len(CASES)))
@pytest.mark.asyncio
async def test_real_search_values_match_pinned_source_native_input(tmp_path, monkeypatch, case):
    from dsh.cordis.context import Context
    from dsh.core.tools import ToolExecutionInput, ToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    from dsh.fs.tool_fs_search import ToolFsSearchPlugin, search_core
    from dsh.subprocess import LocalSubprocessRuntime

    source = ROOT / 'scripts/oracles/official/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe'
    assert source.is_file(), 'Prepare the pinned Source dependency before comparing native inputs'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == 'f9dde63498b3193f098355dbec97af99dc4f6b8fa0df5ed04114a03012c042cb'
    files = {
        'src/main.py': 'hello\nhello 中文\n',
        'src/中文.py': '中文\n',
        'README.md': 'hello readme\n',
        '.hidden.py': 'hidden 中文\n',
        '.git/ignored.py': 'hello 中文\n',
        'ignored.py': 'hello ignored\n',
        '.gitignore': 'ignored.py\n',
    }
    workspace = tmp_path / 'workspace'
    for index, (name, content) in enumerate(files.items()):
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        os.utime(str(path), (1700000000 + index, 1700000000 + index))
    name, arguments = CASES[case]
    rows = []
    previous = search_core._rg_path_cache
    try:
        for binary in (source, BIN / 'rg.exe'):
            monkeypatch.setenv('DSH_RG_PATH', str(binary))
            search_core._rg_path_cache = None
            ctx = Context()
            try:
                SystemPrompt(ctx)
                await ctx.plugin(ToolsPlugin)
                LocalSubprocessRuntime(ctx)
                fiber = await ctx.plugin(ToolFsSearchPlugin, {'sampleOverCapGlobResults': False})
                agent = SimpleNamespace(ctx=fiber.ctx,
                    session=SimpleNamespace(header=SimpleNamespace(id='native-input-comparison', cwd=str(workspace))))
                result = await ctx.get('tools').execute(ToolExecutionInput(
                    'call-' + str(case), name, copy.deepcopy(arguments), agent=agent, signal=asyncio.Event()))
                rows.append(dict(value=result.value, content=result.content))
            finally:
                await ctx.fiber.dispose()
    finally:
        search_core._rg_path_cache = previous
    (tmp_path / 'complete-public-values.json').write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding='utf-8')
    assert rows[0] == rows[1]


@pytest.fixture(scope='module')
def actual_isolated_runtime(tmp_path_factory):
    parent = tmp_path_factory.mktemp('isolated-native-search')
    output = parent / 'runtime.json'
    environment = dict(os.environ)
    environment['PATH'] = ''
    environment.pop('DSH_RG_PATH', None)
    completed = subprocess.run([sys.executable, '-I', '-B',
        str(ROOT / 'scripts/oracles/ripgrep_portable_python.py'), '--root', str(ROOT),
        '--workspace', str(parent / 'workspace'), '--output', str(output)],
        env=environment, capture_output=True, timeout=60)
    (parent / 'process.stdout').write_bytes(completed.stdout)
    (parent / 'process.stderr').write_bytes(completed.stderr)
    assert completed.returncode == 0, completed.stderr
    value = json.loads(output.read_text(encoding='utf-8'))
    assert len(value['modules']) == 114 and set(value['modules']) == REQUIRED_MODULES
    validate_runtime(value, ROOT, sys.executable, value['modules'])
    return value


def damage_runtime(value, damage):
    if damage == 'missing':
        return None
    if damage == 'root':
        value['root'] = str(ROOT.parent)
    elif damage == 'python':
        value['python'] = '3.9.0 unqualified'
    elif damage == 'executable':
        value['executable'] = str(ROOT / 'unqualified/python.exe')
    elif damage == 'binary':
        value['binary'] = str(ROOT / 'rg.exe')
    elif damage == 'binary-sha':
        value['binarySha256'] = '0' * 64
    elif damage == 'path':
        value['path'] = 'host node and rg'
    elif damage == 'override':
        value['explicitOverridePresent'] = True
    elif damage == 'node':
        value['hostNodeFound'] = True
    elif damage == 'version':
        value['version']['stdout'] = value['version']['stdout'].replace('14.1.0', '15.0.0')
    elif damage == 'version-exit':
        value['version']['exitCode'] = 1
    elif damage == 'version-stderr':
        value['version']['stderr'] = 'native load failure'
    elif damage == 'module':
        del value['modules']['dsh/fs/tool_fs_search/search_core.py']
    elif damage == 'module-bytes':
        value['modules']['dsh/fs/tool_fs_search/search_core.py'] = '0' * 64
    elif damage == 'glob':
        value['public'][0]['value']['paths'] = []
    elif damage == 'grep':
        value['public'][1]['value']['matches'][0]['line'] = 'changed result'
    elif damage == 'meta':
        del value['public'][1]['meta']
    elif damage == 'order':
        value['public'].reverse()
    elif damage == 'flag-type':
        value['public'][0]['isError'] = 0
    elif damage == 'public-extra':
        value['public'][0]['extra'] = None
    else:
        raise ValueError('Unknown native-search damage')
    return value


@pytest.mark.parametrize('damage', RUNTIME_DAMAGES)
def test_isolated_native_runtime_rejects_incomplete_receipt(actual_isolated_runtime, damage):
    valid = actual_isolated_runtime
    validate_runtime(valid, ROOT, sys.executable, valid['modules'])
    with pytest.raises((ValueError, KeyError, TypeError)):
        validate_runtime(damage_runtime(copy.deepcopy(valid), damage), ROOT, sys.executable,
                         valid['modules'], check_files=False)
