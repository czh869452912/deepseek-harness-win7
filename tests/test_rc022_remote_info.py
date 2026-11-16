from types import SimpleNamespace

import pytest

from dsh.typert.artifact import Schema,UNDEFINED
from dsh.typert.artifact_current import CurrentSchema,CurrentArtifactParser
from dsh.typert.remote_info import NamedInput,attach_direct_method,is_typert_remote_method
from test_rc022_typert_artifact import generated


def codec(schema=None,**extra):
    return dict(mode='strict',typeSymbol='Text',create=lambda:schema or Schema('string'),jsonSchema=dict(type='string'),**extra)


def parameter(name,source='json',**extra):
    value=codec()
    return dict(name=name,wire=name,source=source,codec=value,strictCodec=value,**extra)


def method(parameters=None,**extra):
    return attach_direct_method(dict(namespace='fixture',method='run',invocation=dict(kind='direct'),
        parameters=[] if parameters is None else parameters,result=codec(),**extra))


def test_named_inputs_cache_separate_views_parsers_and_projections_without_creating_early():
    calls=[]
    def create():calls.append('normal');return Schema('object',[dict(title=Schema('string'))])
    def strict_create():calls.append('strict');return CurrentSchema('strictObject',[dict(title=Schema('string'))])
    ordinary=dict(mode='strict',create=create,jsonSchema=dict(type='object'))
    strict=dict(mode='strict',create=strict_create,jsonSchema=dict(type='object',additionalProperties=False))
    row=method([dict(name='request',wire='request',source='json',codec=ordinary,strictCodec=strict,description='A request.')])
    normal=row['input']();view=row['input'](dict(strict=True))
    assert calls==[] and normal is row['input']({}) is row['input'](dict(strict=1))
    assert normal is not view and view is row['input'](dict(strict=True))
    assert normal.jsonSchema is normal.jsonSchema and normal.jsonSchema['properties']['request']['description']=='A request.'
    assert view.jsonSchema['properties']['request']['additionalProperties'] is False and calls==[]
    assert normal.create() is normal.create() and calls==['normal']
    assert normal.create().parse(dict(request=dict(title='ship',extra=1)))==dict(request=dict(title='ship'))
    with pytest.raises(ValueError):view.create().parse(dict(request=dict(title='ship',extra=1)))
    assert calls==['normal','strict'] and row['parameters'][0]['codec'] is ordinary


def test_named_optional_json_lookup_alias_and_positional_signal_keep_exact_result():
    required=parameter('agent',source='lookup');required['wire']='agentId'
    row=method([required,parameter('label',acceptsUndefined=True)],cancellation=dict(parameter='signal'))
    parser=row['input']().create();value=dict(agentId='agent')
    assert parser.parse(value)==value
    assert parser.parse(dict(value,label=UNDEFINED))==dict(value,label=UNDEFINED)
    assert row['input']().jsonSchema['required']==['agentId']
    for invalid in (None,[],{},dict(agentId=UNDEFINED),dict(value,label=None),dict(value,extra=3)):
        with pytest.raises(ValueError):parser.parse(invalid)
    signal=object();result=object();calls=[]
    class Namespace:
        def run(self,*args):calls.append((self,args));return result
    namespace=Namespace()
    assert row['invoke'](SimpleNamespace(fixture=namespace),value,signal) is result
    assert calls==[(namespace,('agent',UNDEFINED,signal))]


def test_required_unknown_and_lookup_cannot_omit_even_if_codec_accepts_undefined():
    for source in ('json','lookup'):
        row=parameter('value',source=source,acceptsUndefined=source=='lookup')
        row['codec']=row['strictCodec']=codec(Schema('unknown'))
        parser=NamedInput([row],False).create()
        with pytest.raises(ValueError):parser.parse({})
        with pytest.raises(ValueError):parser.parse(dict(value=UNDEFINED))
        assert parser.parse(dict(value=None))==dict(value=None)


def test_empty_method_ignores_signal_keeps_stream_handle_and_current_mount():
    row=method(mode='stream');handle=object();namespace=dict(run=lambda:handle);remote=dict(fixture=namespace)
    assert row['input']().create().parse({})=={} and row['input']().jsonSchema['required']==[]
    assert row['invoke'](remote,{},object()) is handle
    namespace['run']=lambda:(_ for _ in ()).throw(RuntimeError('withdrawn'))
    with pytest.raises(RuntimeError,match='withdrawn'):row['invoke'](remote,{})
    with pytest.raises(TypeError):row['invoke']({}, {})


@pytest.mark.parametrize('error',[UNDEFINED,None,'Unsupported tool type.'])
def test_unavailable_projection_is_independent_from_parser_and_keeps_its_error(error):
    calls=[]
    def create():calls.append(True);raise ValueError('invalid factory')
    value=dict(mode='strict',create=create,jsonSchemaError=error)
    parameter=dict(name='value',wire='alias',source='json',codec=value,strictCodec=value)
    view=NamedInput([parameter],False)
    assert view.jsonSchema is UNDEFINED and calls==[]
    assert view.jsonSchemaError==('Unsupported tool type.' if error=='Unsupported tool type.' else 'No JSON Schema for parameter alias')
    for _ in range(2):
        with pytest.raises(ValueError,match='invalid factory'):view.create()
    assert calls==[True,True]


def test_generated_methods_keep_descriptor_identity_without_context_or_src_invention():
    parser=CurrentArtifactParser(generated('z.string()'));artifact=parser.parse();info=parser.bindings['$remote']
    row=artifact['invocations'][0]
    assert info.package=='fixture' and info.methods['fixture/echo'] is row and is_typert_remote_method(row)
    assert not is_typert_remote_method(dict(row,result=dict(mode='src-json')))
    assert not is_typert_remote_method(dict(row,invoke=None))
    assert not is_typert_remote_method(dict(row,invocation=dict(kind='context')))
    assert not is_typert_remote_method(dict(invocation=dict(kind='direct'),result=dict(mode='strict')))
