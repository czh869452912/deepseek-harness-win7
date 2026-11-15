import errno
import os

import pytest
import yaml

from dsh.boot.config_editor import edit_patch_document, PatchLoader
from dsh.util.atomic_write import write_file_atomic
from scripts.rc022_config_editor_probe import observe


@pytest.mark.asyncio
async def test_actual_profile_editor_persistence_rollback_and_restart(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 10
    assert rows['entries']['values'] == ['config-editor','settings','probe']
    assert rows['updated']['value']['value'] == dict(count=3)
    assert rows['disk']['value'] == [dict(id='probe',name='cordis:probe',config=dict(ordinary='fixed',count=3,token='private'))]
    assert rows['activation-rollback'] == dict(name='activation-rollback', unchanged=True, ordinary='changed')
    assert rows['invalid-refusal']['unchanged'] is True
    assert rows['overlay-refusal']['unchanged'] is True
    assert 'overridden by a home patch or command-line overlay' in rows['overlay-refusal']['message']
    assert rows['restart']['value'] == dict(count=3)
    assert rows['reset']['value'] == dict(count=2)


def test_patch_edit_preserves_untouched_rows_and_restores_expression_tags():
    before = '# profile note\n- id: other\n  # untouched\n  config: {count: 8}\n- id: probe\n  name: cordis:probe\n  config:\n    count: 2\n- id: last\n  disabled: true\n'
    content = edit_patch_document(before, 'probe', 'cordis:probe', dict(count=3,ref=dict(__jsExpr='ctx.value')), {})
    assert content.startswith('# profile note\n- id: other\n  # untouched\n  config: {count: 8}\n')
    assert content.endswith('- id: last\n  disabled: true\n')
    rows = yaml.load(content, Loader=PatchLoader)
    assert rows[1]['config'] == dict(count=3,ref=dict(__jsExpr='ctx.value'))
    assert '!!js' in content
    reset = edit_patch_document(content,'probe','cordis:probe',{}, {})
    assert [row['id'] for row in yaml.load(reset, Loader=PatchLoader)] == ['other','last']


@pytest.mark.asyncio
async def test_atomic_replace_retries_one_windows_sharing_failure_and_leaves_no_temp(tmp_path, monkeypatch):
    from dsh.util import atomic_write
    target = tmp_path/'patch.yml'
    target.write_text('old', encoding='utf-8')
    real = os.replace
    attempts = []
    def replace(source, destination):
        attempts.append(source)
        if len(attempts) == 1:
            raise PermissionError(errno.EACCES, 'busy')
        return real(source, destination)
    monkeypatch.setattr(atomic_write.os,'replace',replace)
    await write_file_atomic(str(target),'new',mode=0o600)
    assert target.read_text(encoding='utf-8') == 'new'
    assert len(attempts) == 2
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.asyncio
async def test_atomic_replace_preserves_original_and_cleans_sibling_on_fatal_failure(tmp_path, monkeypatch):
    from dsh.util import atomic_write
    target = tmp_path/'patch.yml'
    target.write_text('old', encoding='utf-8')
    def refuse(*_):
        raise OSError(errno.ENOSPC,'full')
    monkeypatch.setattr(atomic_write.os,'replace',refuse)
    with pytest.raises(OSError):
        await write_file_atomic(str(target),'new',mode=0o600)
    assert target.read_text(encoding='utf-8') == 'old'
    assert list(tmp_path.iterdir()) == [target]
