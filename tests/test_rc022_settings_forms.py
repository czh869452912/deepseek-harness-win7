import pytest

from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED
from dsh.settings.forms import clone_config, path_edit
from scripts.rc022_settings_forms_probe import observe


@pytest.mark.asyncio
async def test_live_descriptor_revisions_secrets_conflicts_and_inherited_edits():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 11
    assert rows['initial']['value']['revision'] == 0
    assert rows['policy']['value']['autoGenerate'] is False
    assert rows['policy']['value']['revision'] == 0
    assert rows['updated']['value']['revision'] == 2
    assert rows['conflict'] == dict(name='conflict', code='SETTINGS_CONFLICT', expected=0, actual=2)
    assert rows['mutated']['value']['value']['list'] == [dict(name='renamed')]
    assert rows['inherited']['value']['value']['count'] == 2
    assert rows['ordinary-refusal']['message'] == 'Config field "ordinary" is not volatile'
    assert rows['raw']['value']['ordinary'] == 'fixed'
    assert rows['raw']['value']['token'] == 'private'
    assert rows['raw']['value']['list'][0]['token'] == 'secret'
    assert rows['policy-restored']['value']['autoGenerate'] is True
    assert 'token' not in rows['updated']['value']['value']
    assert rows['updated']['value']['secrets'] == [dict(path=['token'], set=True), dict(path=['list','0','token'], set=True)]


@pytest.mark.parametrize('index', ['-1', '01', '2', 'x'])
def test_form_array_path_validation_does_not_mutate_input(index):
    schema = Schema.object(dict(rows=Schema.array(Schema.string()).volatile()))
    raw = dict(rows=['one'])
    with pytest.raises(TypeError, match='out of range'):
        path_edit(raw, dict(op='set', path=['rows', index], value='next'), schema)
    assert raw == dict(rows=['one'])


def test_form_edits_append_remove_default_arrays_and_reject_lossy_inputs():
    schema = Schema.object(dict(rows=Schema.array(Schema.string()).default(['base']).volatile()))
    assert path_edit({}, dict(op='set',path=['rows','1'],value='next'), schema) == dict(rows=['base','next'])
    assert path_edit(dict(rows=['one','two']), dict(op='unset',path=['rows','0']), schema) == dict(rows=['two'])
    assert clone_config(dict(absent=_UNDEFINED, present=None)) == dict(present=None)
    cyclic = {}
    cyclic['self'] = cyclic
    with pytest.raises(TypeError, match='circular'):
        clone_config(cyclic)
    with pytest.raises(TypeError, match='undefined'):
        clone_config(dict(rows=[_UNDEFINED]))
    with pytest.raises(TypeError, match='non-finite'):
        clone_config(dict(value=float('nan')))
