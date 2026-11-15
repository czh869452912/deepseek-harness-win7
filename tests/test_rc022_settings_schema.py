import pytest

from dsh.cordis.schema import Schema
from dsh.settings.schema_current import plain_config, project_form, volatile_form
from scripts.rc022_settings_schema_probe import observe


@pytest.mark.asyncio
async def test_live_settings_schema_projection_preserves_expressions_and_redacts_defaults():
    rows = {row['name']: row for row in await observe()}
    assert rows['nested']['value'] == dict(nested=dict(live=3), enabled=True)
    assert rows['paths']['values'] == [True, False, False, True]
    assert rows['expression']['value'] == dict(nested=dict(__jsExpr='ctx.live'))
    assert rows['empty'] == dict(name='empty', form=None, value={})
    assert rows['null']['value'] is None
    assert 'hidden' not in str(rows['container']['schema'])
    assert rows['container']['value']['secret'] == 'private'
    assert rows['original'] == dict(name='original', secretDefault='hidden', volatile=True)


def test_form_projection_does_not_mutate_original_live_schema_or_values():
    schema = Schema.object(dict(rows=Schema.array(Schema.object(dict(
        secret=Schema.string().role('secret').default('hidden'), label=Schema.string()))).volatile()))
    form = volatile_form(schema)
    assert form.dict['rows'].meta.get('volatile') is None
    assert schema.dict['rows'].meta['volatile'] is True
    assert schema.dict['rows'].inner.dict['secret'].meta['default'] == 'hidden'
    raw = schema(dict(rows=[dict(secret='private', label='one')]))
    detached = plain_config(raw)
    detached['rows'][0]['label'] = 'changed'
    assert plain_config(raw)['rows'][0]['label'] == 'one'
    assert project_form(form, dict(rows=[], hidden=True)) == dict(rows=[])
