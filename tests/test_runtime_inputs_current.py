"""Current metadata must remain pinned without erasing Native installation edges."""
import copy
import json
from pathlib import Path

import pytest

from scripts import build_portable, runtime_inputs_current as inputs

ROOT = Path(__file__).resolve().parents[1]


def test_current_roster_preserves_distinct_historical_identity():
    manifest = json.loads((ROOT / 'scripts/runtime-inputs.json').read_text(encoding='utf-8'))
    inputs.validate(ROOT, manifest, inputs.TARGET)
    history = json.loads((ROOT / inputs.HISTORY).read_text(encoding='utf-8'))
    old = {row['path']: row for row in history['files'] + history.get('native_files', [])}
    assert manifest['previous_manifest_sha256'] == inputs.sha(ROOT / inputs.HISTORY)
    retained = [row for row in manifest['files'] if row['origin'] == 'retained-compatibility']
    assert retained
    for row in retained:
        assert row['source_upstream'] == history['target_upstream'] != inputs.TARGET
        assert row['sha256'] == old[row['path']]['sha256']
    overlays = {row['path'] for row in manifest['files'] if row['origin'] == 'product-overlay'}
    assert overlays == set(inputs.OVERLAYS)


@pytest.mark.parametrize('damage', ['duplicate', 'extra', 'bytes', 'source', 'drive', 'null-source'])
def test_current_runtime_damage_is_rejected(tmp_path, damage):
    target = tmp_path / 'apps/cli/package.json'
    target.parent.mkdir(parents=True)
    target.write_text('{}', encoding='utf-8')
    row = dict(path='apps/cli/package.json', sha256=inputs.sha(target),
               origin='current-source', source_upstream=inputs.TARGET, source_sha256='a' * 64)
    manifest = dict(schema_version=2, target_upstream=inputs.TARGET, files=[row])
    inputs.validate(tmp_path, manifest, inputs.TARGET)
    if damage == 'duplicate': manifest['files'].append(copy.deepcopy(row))
    if damage == 'extra':
        extra = tmp_path / 'packages/test/extra/package.json'
        extra.parent.mkdir(parents=True)
        extra.write_text('{}', encoding='utf-8')
    if damage == 'bytes': target.write_text('{"changed":true}', encoding='utf-8')
    if damage == 'source': row['source_upstream'] = 'old'
    if damage == 'drive': row['path'] = 'C:apps/cli/package.json'
    if damage == 'null-source': row['source_sha256'] = None
    with pytest.raises(ValueError): inputs.validate(tmp_path, manifest, inputs.TARGET)


def test_portable_keeps_native_creative_installation_closure(tmp_path):
    native = tmp_path / 'checkout/apps/cli/package.json'
    original = tmp_path / 'checkout/reference/apps/cli/package.json'
    native.parent.mkdir(parents=True)
    original.parent.mkdir(parents=True)
    native.write_text('{"dependencies":{"@deepseek-win7/dsh-creative":"workspace:*"}}', encoding='utf-8')
    original.write_text('{"dependencies":{}}', encoding='utf-8')
    destination = tmp_path / 'portable'
    build_portable.bundle_application_metadata(tmp_path / 'checkout', destination)
    assert (destination / 'package.json').read_bytes() == native.read_bytes()
    assert (destination / 'apps/cli/package.json').read_bytes() == native.read_bytes()
