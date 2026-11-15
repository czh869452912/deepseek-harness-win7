import pytest

from dsh.interaction.commands import normalize_definition
from dsh.sdk.query_input import query_command, query_content, query_command_images
from scripts import rc022_sdk_input_probe as probe


@pytest.mark.asyncio
async def test_current_catalog_identity_and_input_observations(tmp_path):
    probe.WORKSPACE=tmp_path
    rows=await probe.observe();catalog=rows[0]['value']
    assert len(rows)==276
    assert next(row for row in catalog if row['name']=='wish')['definitionId']=='@deepseek-ai/dsh-command-goal'
    assert 'definitionId' not in next(row for row in catalog if row['name']=='goal')
    routes={row['text']:row['value'] for row in rows if row['name']=='route'}
    assert routes['/goal arg'] is None and routes['/目标 arg']=='/wish arg'
    assert routes['/压缩']=='/compress' and routes['/压缩 arg'] is None
    assert routes['/权限'] is None and routes['/权限\u00a0arg']=='/access arg'
    assert routes['/计划\u0085arg'] is None and routes['/计划\u2028arg']=='/design arg'


def test_definition_identity_is_immutable_and_optional():
    def handler(_):return dict(kind='success')
    registration=normalize_definition(dict(name='renamed',description='identity',definitionId='@deepseek-ai/dsh-plan-mode',handler=handler))
    assert registration.definition.definitionId==registration.descriptor.definitionId
    with pytest.raises(AttributeError):registration.descriptor.definitionId='other'
    with pytest.raises(AttributeError):registration.definition.definitionId='other'
    assert query_command('/计划 on',[registration.descriptor])=='/renamed on'
    absent=normalize_definition(dict(name='plan',description='third party',handler=handler))
    assert 'definitionId' not in absent.descriptor.to_dict()
    assert query_command('/plan on',[absent.descriptor,registration.descriptor]) is None


def test_input_admission_preserves_extensible_data_and_exact_text_identity():
    source=[dict(type='custom',value=dict(items=[1])),dict(type='text',text='x')]
    copied=query_content(source)
    assert copied==source and copied[0] is not source[0]
    command=dict(type='text',text='/plan');encoded=dict(type='image',data='AA==',mimeType='image/png')
    assert query_command_images([encoded,command,encoded],command)==[encoded,encoded]
    with pytest.raises(TypeError,match='one text block'):query_command_images([command,dict(command)],command)
