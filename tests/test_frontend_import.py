import copy
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts import import_frontend as frontend


ROOT = Path(__file__).resolve().parents[1]


def test_actual_pinned_official_frontend_has_complete_build_provenance():
    manifest = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    record, paths = frontend.recorded_inputs(ROOT / 'reference', manifest['target_upstream'])
    assert record == manifest['build_record']
    assert {path.relative_to(ROOT / 'reference').as_posix(): frontend.digest(path) for path in paths} == {
        row['path']: row['sha256'] for row in manifest['files'] + manifest['client_files']}
    frontend.validate_import(ROOT, manifest)
    with pytest.raises(ValueError, match='unchanged pinned'):
        frontend.recorded_inputs(ROOT / 'reference', '0' * 40)


@pytest.mark.parametrize('damage', ['missing-client', 'changed-client', 'extra-client', 'changed-shell',
    'missing-shell', 'extra-shell', 'duplicate-row', 'wrong-count', 'wrong-digest', 'wrong-pin',
    'wrong-profile', 'wrong-title', 'missing-version', 'extra-record-field'])
def test_complete_frontend_record_refuses_changed_or_incomplete_inputs(tmp_path, damage):
    payloads = {'apps/web/dist/index.html': b'original shell',
                'packages/client/connection/lib/client.js': b'original connection',
                'packages/client/connection/lib/client.js.map': b'original map'}
    for name, content in payloads.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    pinned = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    manifest = copy.deepcopy(pinned)
    manifest['files'] = [dict(path=name, sha256=frontend.digest(tmp_path / name))
                         for name in payloads if name.startswith('apps/')]
    manifest['client_files'] = [dict(path=name, sha256=frontend.digest(tmp_path / name))
                                for name in payloads if name.startswith('packages/')]
    manifest['build_record']['artifacts'] = frontend.build_digest(tmp_path, frontend.artifact_paths(tmp_path))
    frontend.validate_import(tmp_path, manifest)
    if damage in ('missing-client', 'missing-shell'):
        (tmp_path / next(name for name in payloads if name.startswith('packages/' if damage == 'missing-client' else 'apps/'))).unlink()
    elif damage in ('changed-client', 'changed-shell'):
        (tmp_path / next(name for name in payloads if name.startswith('packages/' if damage == 'changed-client' else 'apps/'))).write_bytes(b'changed')
    elif damage in ('extra-client', 'extra-shell'):
        path = tmp_path / ('packages/client/unknown/lib/client.js' if damage == 'extra-client' else 'apps/web/dist/stale.js')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'extra')
    elif damage == 'duplicate-row':
        manifest['client_files'].append(copy.deepcopy(manifest['client_files'][0]))
    elif damage in ('wrong-count', 'wrong-digest'):
        manifest['build_record']['artifacts']['fileCount' if damage == 'wrong-count' else 'sha256'] = 0
    elif damage == 'extra-record-field':
        manifest['build_record']['unknown'] = True
    else:
        keys = {'wrong-pin': 'DSH_CLIENT_COMMIT_HASH', 'wrong-profile': 'DSH_CLIENT_BUILD_PROFILE',
                'wrong-title': 'DSH_CLIENT_TITLE', 'missing-version': 'DSH_CLIENT_VERSION'}
        manifest['build_record']['environment'][keys[damage]] = ''
    with pytest.raises(ValueError, match='frontend'):
        frontend.validate_import(tmp_path, manifest)


def test_original_client_artifact_patterns_include_browser_chunks_and_assets_but_exclude_node(tmp_path):
    names = ['apps/web/dist/index.html', 'apps/web/dist/client.node.js', 'packages/api/gateway/lib/client.js',
             'packages/api/gateway/lib/client.browser.js', 'packages/api/gateway/lib/client.browser.js.map',
             'packages/api/gateway/lib/client.chunk-123.js', 'packages/api/gateway/lib/client.chunk-123.js.map',
             'packages/api/gateway/lib/assets/nested/module.wasm', 'packages/api/gateway/lib/assets/client.node.js']
    excluded = ['packages/api/gateway/lib/client.node.js', 'packages/api/gateway/lib/client.node.js.map',
                'packages/api/gateway/lib/index.js', 'packages/api/gateway/lib/types/private.js']
    for name in names + excluded:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode('utf-8'))
    assert {path.relative_to(tmp_path).as_posix() for path in frontend.artifact_paths(tmp_path)} == set(names)


def test_import_preflight_only_accepts_new_staged_members_from_verified_target(tmp_path):
    shell, client = 'apps/web/dist/index.html', 'packages/client/test/lib/client.js'
    for name in (shell, client):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'original')
    pinned = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    manifest = copy.deepcopy(pinned)
    manifest.update(files=[dict(path=shell, sha256=frontend.digest(tmp_path / shell))],
                    client_files=[dict(path=client, sha256=frontend.digest(tmp_path / client))])
    manifest['build_record']['artifacts'] = frontend.build_digest(tmp_path, frontend.artifact_paths(tmp_path))
    extra = tmp_path / 'packages/client/test/lib/client.browser.js'
    extra.write_bytes(b'new approved Source member')
    allowed = {extra.relative_to(tmp_path).as_posix(): frontend.digest(extra)}
    with pytest.raises(ValueError, match='frontend'):
        frontend.validate_import(tmp_path, manifest)
    frontend.validate_import(tmp_path, manifest, staged=allowed)
    extra.write_bytes(b'unknown bytes')
    with pytest.raises(ValueError, match='frontend'):
        frontend.validate_import(tmp_path, manifest, staged=allowed)
    allowed[extra.relative_to(tmp_path).as_posix()] = frontend.digest(extra)
    (tmp_path / client).write_bytes(b'changed old member')
    allowed[client] = frontend.digest(tmp_path / client)
    with pytest.raises(ValueError, match='frontend'):
        frontend.validate_import(tmp_path, manifest, staged=allowed)


@pytest.mark.parametrize('changed_record', [False, True])
def test_cli_import_backs_up_and_retires_obsolete_client_assets(tmp_path, monkeypatch, changed_record):
    root, source = tmp_path / 'product', tmp_path / 'source'
    root.mkdir()
    source.mkdir()
    def write(base, name, data):
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    write(source, '.gitignore', b'.dsh-build/\n')
    write(source, 'package.json', b'{"version":"0.0.0-test"}')
    new = {'apps/web/dist/index.html': b'new shell', 'packages/client/shared/lib/client.js': b'new client',
           'packages/client/shared/lib/client.browser.js': b'staged browser',
           'packages/client/shared/lib/assets/module.wasm': b'new asset'}
    for name, data in new.items():
        write(source, name, data)
    for arguments in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture']):
        subprocess.run(['git', '-C', str(source)] + arguments, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    pin = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    def manifest(base, target):
        paths = frontend.artifact_paths(base)
        return dict(target_upstream=target, kind='versioned-prebuilt-input', build_record=dict(formatVersion=1,
                    environment=dict(DSH_CLIENT_BUILD_PROFILE='official', DSH_CLIENT_COMMIT_HASH=target[:7],
                                     DSH_CLIENT_TITLE='DeepSeek Harness', DSH_CLIENT_VERSION='0.0.0-test'),
                    artifacts=frontend.build_digest(base, paths)),
                    files=[dict(path=p.relative_to(base).as_posix(), sha256=frontend.digest(p)) for p in paths if p.relative_to(base).parts[0]=='apps'],
                    client_files=[dict(path=p.relative_to(base).as_posix(), sha256=frontend.digest(p)) for p in paths if p.relative_to(base).parts[0]=='packages'])
    write(source, '.dsh-build/client-build-environment.json', json.dumps(manifest(source, pin)['build_record']).encode('utf-8'))
    old = {'apps/web/dist/index.html': b'old shell', 'packages/client/shared/lib/client.js': b'old client',
           'packages/client/obsolete/lib/client.js': b'obsolete client'}
    for name, data in old.items():
        write(root, name, data)
    write(root, 'scripts/frontend-inputs.json', json.dumps(manifest(root, 'a' * 40)).encode('utf-8'))
    old_record = json.dumps(manifest(root, 'a' * 40)['build_record']).encode('utf-8')
    write(root, 'scripts/frontend-build-record.json', b'{}' if changed_record else old_record)
    write(root, 'migration/baseline.json', json.dumps(dict(target_upstream=pin)).encode('utf-8'))
    write(root, 'packages/client/shared/lib/client.browser.js', new['packages/client/shared/lib/client.browser.js'])
    output = root / '.goose/out/import'
    monkeypatch.setattr(frontend, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['import_frontend.py', '--source', str(source), '--output-dir', str(output)])
    if changed_record:
        with pytest.raises(ValueError, match='previous frontend build record differs'):
            frontend.main()
        assert (root / 'apps/web/dist/index.html').read_bytes() == old['apps/web/dist/index.html']
        assert (root / 'scripts/frontend-build-record.json').read_bytes() == b'{}'
        return
    frontend.main()
    assert not (root / 'packages/client/obsolete/lib/client.js').exists()
    for name, data in new.items():
        assert (root / name).read_bytes() == data
    with zipfile.ZipFile(str(output / 'previous-artifacts.zip')) as zipped:
        assert zipped.read('scripts/frontend-build-record.json') == old_record
        for name, data in old.items():
            assert zipped.read(name) == data
    frontend.validate_import(root, json.loads((root / 'scripts/frontend-inputs.json').read_text(encoding='utf-8')))
    assert (root / 'scripts/frontend-build-record.json').read_bytes() == (source / '.dsh-build/client-build-environment.json').read_bytes()
    from scripts.prepare_reference import restore_frontend
    restored = restore_frontend(root, source)
    assert restored['restored'] == [] and restored['buildRecord'] == json.loads(
        (root / 'scripts/frontend-build-record.json').read_text(encoding='utf-8'))
    assert restored['originalCarrier'] is None and restored['sha256'] is None
