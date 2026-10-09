"""Exercise source and Portable resolution without a developer PATH."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest

from dsh.fs.tool_fs_search import search_core as core


@pytest.mark.parametrize('winner', ['explicit', 'sidecar', 'portable', 'linked', 'pnpm'])
def test_fixed_resolution_precedence_without_path(tmp_path, monkeypatch, winner):
    package = tmp_path / 'dsh/fs/tool_fs_search'
    package.mkdir(parents=True)
    monkeypatch.setattr(core, '__file__', str(package / 'search_core.py'))
    monkeypatch.setattr(core.sys, 'executable', str(tmp_path / 'python.exe'))
    monkeypatch.setattr(core.sys, 'platform', 'win32')
    monkeypatch.setattr(core.platform, 'machine', lambda: 'AMD64')
    monkeypatch.setattr(core.shutil, 'which', lambda _: None)
    monkeypatch.setattr(core, '_rg_path_cache', None)
    monkeypatch.delenv('DSH_RG_PATH', raising=False)
    candidates = dict(explicit=tmp_path / 'override.exe', sidecar=tmp_path / 'python.exe-rg',
        portable=package / 'bin/rg.exe',
        linked=tmp_path / 'reference/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe',
        pnpm=tmp_path / 'reference/node_modules/.pnpm/@vscode+ripgrep-win32-x64@1.18.0/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe')
    remaining = False
    for name, target in candidates.items():
        remaining |= name == winner
        if remaining:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'resolution fixture')
    if winner == 'explicit':
        monkeypatch.setenv('DSH_RG_PATH', str(candidates[winner]))
    assert asyncio.run(core.resolve_rg_path()) == str(candidates[winner])


@pytest.mark.skipif(sys.platform != 'win32', reason='fixed Windows development input')
def test_fresh_source_glob_and_grep_have_no_host_rg(tmp_path):
    (tmp_path / '中文.txt').write_text('独立搜索\n', encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PATH='')
    env.pop('DSH_RG_PATH', None)
    script = '''
import asyncio, hashlib, subprocess, sys
from pathlib import Path
from dsh.fs.tool_fs_search.search_core import resolve_rg_path
rg = asyncio.run(resolve_rg_path())
assert Path(rg).resolve() == Path('dsh/fs/tool_fs_search/bin/rg.exe').resolve(), rg
assert hashlib.sha256(Path(rg).read_bytes()).hexdigest() == '1dce02aae98c0a48c2644abd1849fb90406296d4e0c95e239f95242ee8480ff8'
assert subprocess.check_output([rg, '--version']).decode('utf-8').splitlines()[0].startswith('ripgrep 14.1.0 ')
for args in (['--files', '--hidden', '--no-ignore', sys.argv[1]],
             ['--json', '独立搜索', sys.argv[1]]):
    result = subprocess.run([rg, '--no-config'] + args, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=True)
    assert '中文.txt' in result.stdout.decode('utf-8'), result.stdout
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], cwd=str(root),
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
