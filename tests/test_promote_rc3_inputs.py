import json
import hashlib
from pathlib import Path
import zipfile
import pytest
import yaml
from scripts import promote_rc3_inputs as tool
from dsh.cordis.loader import js_constructor


class RuntimeYaml(yaml.SafeLoader):
    pass


RuntimeYaml.add_constructor('tag:yaml.org,2002:js', js_constructor)


def test_wrong_source_is_refused_before_runtime_inputs_are_read(tmp_path, monkeypatch):
    monkeypatch.setattr(tool.subprocess, 'check_output', lambda *args, **kwargs: '0' * 40)
    with pytest.raises(ValueError, match='Unchanged pinned'):
        tool.selected_inputs(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_import_preserves_exact_old_bytes_and_only_applies_declared_product_overlays(tmp_path, monkeypatch):
    minimal='packages/preset/agent-presets/presets/minimal/agent.cordis.yml'
    sdk='packages/bundle/sdk-minimal/cordis.patch.yml'
    metadata='packages/preset/agent-presets/presets/minimal/preset.yml'
    values={minimal:b'- id: persona\n  config:\n    prefix: helpful\n', sdk:b'- insert:\n    - id: original\n',metadata:b'name: minimal\n',
            'apps/cli/package.json':b'{"version":"0.1.5-rc.3"}\n'}
    old=b'# The bare local filesystem shadows the host.\n- id: filesystem\n  config: []\n'
    p=tmp_path/minimal;p.parent.mkdir(parents=True);p.write_bytes(old)
    monkeypatch.setattr(tool,'selected_inputs',lambda source:dict(values))
    report=tool.import_inputs(tmp_path/'source',tmp_path,tmp_path/'.goose/out/import')
    with zipfile.ZipFile(str(tmp_path/'.goose/out/import/previous-runtime-inputs.zip')) as z:
        assert z.read(minimal)==old
    assert (tmp_path/'apps/cli/package.json').read_bytes()==values['apps/cli/package.json']
    assert yaml.safe_load((tmp_path/minimal).read_text(encoding='utf-8'))[-1]['id']=='filesystem'
    sdk_rows = yaml.load((tmp_path/sdk).read_text(encoding='utf-8'), Loader=RuntimeYaml)[0]['insert']
    assert [row['id'] for row in sdk_rows]==['original','fs-local','str-replace-editor']
    assert sdk_rows[1]['config']['cwd'] == {'__jsExpr': 'process.env.DSH_CWD ?? process.cwd()'}
    assert sum(row['product_overlay'] for row in report['files'])==3
    assert json.loads((tmp_path/'.goose/out/import/report.json').read_text(encoding='utf-8'))==report
    tool.validate_runtime_inputs(tmp_path,report,tool.TARGET)
    (tmp_path/'apps/cli/package.json').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Runtime input differs'):
        tool.validate_runtime_inputs(tmp_path,report,tool.TARGET)


def test_output_outside_owned_verification_tree_is_refused(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'selected_inputs',lambda source:{})
    with pytest.raises(ValueError): tool.import_inputs(tmp_path/'source',tmp_path,tmp_path/'unowned')
    assert not (tmp_path/'unowned').exists()


@pytest.mark.parametrize('damage', ['none', 'skill', 'native', 'source', 'extra', 'ownership', 'scope'])
def test_reimport_preserves_only_reviewed_creative_overlay_and_native_resources(tmp_path, monkeypatch, damage):
    minimal = 'packages/preset/agent-presets/presets/minimal/agent.cordis.yml'
    sdk = 'packages/bundle/sdk-minimal/cordis.patch.yml'
    metadata = 'packages/preset/agent-presets/presets/minimal/preset.yml'
    selected = {minimal: b'- id: persona\n', sdk: b'- insert:\n    - id: original\n', metadata: b'name: minimal\n',
                tool.CREATIVE_SKILL: b'Original TS development guidance\n'}
    native_name = tool.CREATIVE_DIR + 'references/python-api.md'
    native_skill = b'Python 3.8.10 development guidance\r\n'
    for name, data in [(minimal, b'# The bare local filesystem shadows the host.\n- id: filesystem\n'),
                       (tool.CREATIVE_SKILL, native_skill), (native_name, b'Python Context bindings\n')]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    source_hash = digest(selected[tool.CREATIVE_SKILL])
    manifest = dict(target_upstream=tool.TARGET, files=[dict(path=tool.CREATIVE_SKILL,
        source_sha256=source_hash, sha256=digest(native_skill), product_overlay=True)],
        native_files=[dict(path=native_name, sha256=digest((tmp_path/native_name).read_bytes()), product_owned=True)])
    if damage in ('skill', 'native'):
        (tmp_path / (tool.CREATIVE_SKILL if damage == 'skill' else native_name)).write_bytes(b'unreviewed')
    elif damage == 'source':
        selected[tool.CREATIVE_SKILL] = b'Changed upstream guidance'
    elif damage == 'extra':
        (tmp_path / tool.CREATIVE_DIR / 'unregistered.md').write_text('not reviewed', encoding='utf-8')
    elif damage == 'ownership':
        manifest['native_files'][0]['product_owned'] = False
    elif damage == 'scope':
        manifest['native_files'][0]['path'] = 'packages/unrelated/payload.py'
    (tmp_path/'scripts').mkdir()
    (tmp_path/'scripts/runtime-inputs.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(tool, 'selected_inputs', lambda _: dict(selected))
    before = (tmp_path / tool.CREATIVE_SKILL).read_bytes()
    if damage != 'none':
        with pytest.raises(ValueError):
            tool.import_inputs(tmp_path/'source', tmp_path, tmp_path/'.goose/out/import')
        assert (tmp_path/tool.CREATIVE_SKILL).read_bytes() == before
        return
    report = tool.import_inputs(tmp_path/'source', tmp_path, tmp_path/'.goose/out/import')
    assert (tmp_path/tool.CREATIVE_SKILL).read_bytes() == native_skill
    row = next(r for r in report['files'] if r['path'] == tool.CREATIVE_SKILL)
    assert row['source_sha256'] == source_hash and row['product_overlay']
    assert report['native_files'] == manifest['native_files']
    assert tool.CREATIVE_ADAPTATION in report['adaptations']
    tool.validate_runtime_inputs(tmp_path, report, tool.TARGET)
