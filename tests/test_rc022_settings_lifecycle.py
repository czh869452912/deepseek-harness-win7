import pytest
import yaml

from dsh.boot.config_editor import edit_patch_document, PatchLoader
from scripts.rc022_settings_lifecycle_probe import observe


@pytest.mark.asyncio
async def test_settings_hmr_transactions_comments_and_one_time_legacy_import(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 13
    assert rows['comments']['values'] == [True] * 5
    assert rows['serialized-edits'] == dict(name='serialized-edits', value=4, token='rotated')
    assert rows['activation-rollback']['unchanged'] is True
    assert rows['restart']['value'] == dict(count=4)
    assert rows['reset']['value'] == dict(count=2)
    assert rows['legacy-import'] == dict(name='legacy-import',renamed=True,value=6)
    imported = tmp_path/'native/settings.yaml.imported'
    assert yaml.safe_load(imported.read_text(encoding='utf-8')) == dict(probe=dict(count=6),missing=dict(enabled=True))


@pytest.mark.parametrize('config', ['{count: 2}', '\n    count: 2\n    token: private'])
def test_config_value_replacement_preserves_own_row_comments_and_metadata(config):
    before = '# profile\n- id: probe # identity\n  name: cordis:probe # module\n  # form\n  config: '+config+' # value\n  disabled: false # enabled\n# tail\n'
    result = edit_patch_document(before,'probe','cordis:probe',dict(count=3), {})
    for marker in ('# profile','# identity','# module','# form','# value','# enabled','# tail'):
        assert marker in result
    row = yaml.load(result,Loader=PatchLoader)[0]
    assert row['config'] == dict(count=3)
    assert row['disabled'] is False


def test_config_insert_into_row_preserves_its_comment_and_existing_keys():
    before = '- id: probe # identity\n  name: cordis:probe # module\n  disabled: false # keep\n'
    result = edit_patch_document(before,'probe','cordis:probe',dict(count=3), {})
    assert yaml.load(result,Loader=PatchLoader) == [dict(id='probe',name='cordis:probe',disabled=False,config=dict(count=3))]
    assert '# identity' in result and '# module' in result and '# keep' in result
