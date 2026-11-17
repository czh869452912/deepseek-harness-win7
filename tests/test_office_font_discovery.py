import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.office.font_discovery import host_font_volume, system_font_directories
from dsh.office.font_volume import FontVolume


def test_actual_source_system_roots():
    root = Path(__file__).resolve().parents[1]
    node = os.environ.get('DSH_TEST_OFFICE_NODE')
    if not node:
        pytest.skip('Explicit Office Source/Node qualification inputs required.')
    cases = [dict(platform='win32', home='C:\\Users\\Owner', env=env) for env in
             ({}, {'SystemRoot': 'D:\\Windows'}, {'LOCALAPPDATA': 'D:\\Private'},
              {'SystemRoot': '\\\\server\\os', 'LOCALAPPDATA': '\\\\server\\profile'},
              {'SystemRoot': 'C:/Base/../Windows', 'LOCALAPPDATA': 'D:/User/./Local'})]
    cases += [dict(platform='linux', home='/home/owner', env=env) for env in
              ({}, {'XDG_DATA_DIRS': '/one::/one:/two', 'XDG_DATA_HOME': '/private'}, {'XDG_DATA_DIRS': ''},
               {'XDG_DATA_DIRS': '/one/../two:/two', 'XDG_DATA_HOME': '/home/./private'})]
    command = [node, str(root / 'scripts/oracles/rc022_office_font_roots.mjs'), str(root / '.goose/out/rc022-prep-20261114-01/source')]
    result = subprocess.run(command, input=json.dumps(cases).encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
    assert result.returncode == 0, result.stdout.decode('utf-8', 'replace')
    rows = json.loads(result.stdout)
    assert [system_font_directories(**row['request']) for row in rows] == [row['roots'] for row in rows]


def test_explicit_empty_directories_disable_office_discovery(tmp_path):
    env = dict(ProgramFiles=str(tmp_path), LOCALAPPDATA=str(tmp_path), SystemRoot=str(tmp_path))
    volume, host = host_font_volume(dict(fontDirectories=[]), env=env)
    assert volume.paths == [] and volume.assets == {} and volume.directories == {}
    assert host['env'] == {}


def test_directory_inventory_keeps_dirent_types_and_physical_names(tmp_path):
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'font.ttf').write_bytes(b'font')
    (tmp_path / 'ignored.txt').write_bytes(b'nonfont')
    volume = FontVolume([str(tmp_path)], include_directories=True)
    entries = volume.manifest()['directories']['/physical/' + os.path.realpath(str(tmp_path))]
    assert {row['name']: row['kind'] for row in entries} == dict(nested='directory', **{'font.ttf': 'file', 'ignored.txt': 'file'})
    assert len(volume.assets) == 1
