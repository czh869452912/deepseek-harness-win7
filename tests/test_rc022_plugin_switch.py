import pytest
import yaml

from dsh.boot.plugin_switch import edit_enabled_document, write_plugin_enabled
from scripts.rc022_plugin_switch_probe import observe


@pytest.mark.asyncio
async def test_persisted_switch_semantics_comments_anchors_and_idempotence(tmp_path):
    rows = {row['name']: row['steps'] for row in await observe(tmp_path)}
    assert len(rows) == 32
    for name in ('malformed', 'mapping', 'duplicate'):
        assert all(step == dict(refused=True, unchanged=True) for step in rows[name])
    for name in ('anchor-value', 'anchor-map', 'anchor-key', 'alias-value', 'anchored-disabled'):
        assert not rows[name][0].get('refused'), name
        assert rows[name][0]['patches'][0 if name != 'alias-value' else 1]['disabled'] is False
    assert rows['header-only'][0]['patches'] == []
    assert rows['header-only'][0]['comments'] == ['# header']
    assert rows['last-comment'][0]['comments'] == ['# about tool', '# tail']
    assert rows['comment-expression'][0]['expression']
    assert rows['comment-expression'][0]['comments'] == ['# personal configuration', '# availability']
    assert rows['plain'][1]['unchanged'] and not rows['plain'][1]['changed']
    assert rows['overridden'][0]['patches'] == []
    assert rows['bundle-null'][0]['patches'] == []
    assert rows['bundle-condition'][0]['patches'] == [dict(id='tool', disabled=False)]
    assert rows['nested-group'][0]['patches'] == [dict(id='tool', disabled=True)]
    assert rows['anchor-map'][0]['patches'][1]['config']['target']['disabled'] is False
    assert rows['anchored-disabled'][0]['patches'][1]['config']['flag'] is False


def test_preserves_unrelated_yaml_bytes_and_replaces_only_switch_scalar():
    text = '# header\n- id: tool\n  name: package\n  config: { value: !!js process.platform }\n  disabled: false # available\n- id: other\n  config: {count: 8}\n'
    changed, content = edit_enabled_document(text, 'tool', 'package', False, [])
    assert changed
    assert content == text.replace('disabled: false', 'disabled: true')
    changed, content2 = edit_enabled_document(content, 'tool', 'package', False, [])
    assert not changed and content2 == content


@pytest.mark.asyncio
async def test_unreadable_directory_is_never_replaced(tmp_path):
    directory = tmp_path/'cordis.patch.yml'
    directory.mkdir()
    with pytest.raises(OSError):
        await write_plugin_enabled(dict(patchPath=str(directory)), 'tool', 'package', True)
    assert directory.is_dir()
