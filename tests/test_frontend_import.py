import copy
import json
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
