import json
from pathlib import Path

import pytest

from scripts import prepare_reference

ROOT = Path(__file__).resolve().parents[1]


def test_cold_preparation_builds_every_client_index_embedded_in_sealed_frontend():
    required = set()
    for path in (ROOT / 'apps/web/dist').rglob('*.js.map'):
        document = json.loads(path.read_text(encoding='utf-8'))
        for source, content in zip(document['sources'], document['sourcesContent']):
            if content is not None and '/packages/client/' in source and source.endswith('/lib/index.js'):
                required.add(source.split('/packages/client/', 1)[1].split('/', 1)[0])
    assert required, 'Sealed frontend must declare its actual library inputs'
    assert required.issubset(prepare_reference.STATIC_CLIENT_LIBRARIES)


def test_original_sealed_frontend_restores_cold_ignored_tree_and_refuses_changed_observation(tmp_path, monkeypatch):
    source = tmp_path / 'reference'
    source.mkdir()
    source.joinpath('package.json').write_bytes((ROOT / 'reference/package.json').read_bytes())
    target = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))['target_upstream']
    monkeypatch.setattr(prepare_reference.subprocess, 'check_output',
                        lambda command, **kwargs: target + '\n' if command[-1] == 'HEAD' else '')
    result = prepare_reference.restore_frontend(ROOT, source)
    manifest = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    assert len(result['restored']) == len(manifest['files']) + len(manifest['client_files']) + 1
    assert prepare_reference.restore_frontend(ROOT, source)['restored'] == []
    shell = source / 'apps/web/dist/index.html'
    shell.write_bytes(b'changed actual observation')
    with pytest.raises(ValueError, match='existing different observation'):
        prepare_reference.restore_frontend(ROOT, source)
    assert shell.read_bytes() == b'changed actual observation'


def test_frontend_restore_refuses_wrong_source_before_creating_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_reference.subprocess, 'check_output', lambda *args, **kwargs: '0' * 40)
    with pytest.raises(ValueError, match='unchanged pinned Source'):
        prepare_reference.restore_frontend(ROOT, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_preparation_refuses_wrong_source_before_package_manager_or_build(tmp_path, monkeypatch):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/frontend-inputs.json').write_text(json.dumps({'target_upstream':'1' * 40}), encoding='utf-8')
    monkeypatch.setattr(prepare_reference, 'ROOT', tmp_path)
    monkeypatch.setattr(prepare_reference.sys, 'argv', ['prepare_reference.py','--output',str(tmp_path / 'output')])
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return '0' * 40
    monkeypatch.setattr(prepare_reference.subprocess, 'check_output', run)
    with pytest.raises(ValueError, match='before install/build'):
        prepare_reference.main()
    assert all(command[0] == 'git' for command in commands)
    assert list((tmp_path / 'output').iterdir()) == []
