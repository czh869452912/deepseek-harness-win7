import json

import pytest

from dsh.typert.artifact import UNDEFINED,read_generated_artifact
from dsh.typert.artifact_current import CurrentArtifactParser,CodecSchema,SchemaFactory,CurrentSchema
from dsh.typert.loader import validate_manifest

PREFIX="import { z } from 'zod'\nimport { createTypertRemoteInfo } from '@deepseek-ai/dsh-typert-protocol/remote-info'\n"


def generated(schema):
    return PREFIX+'''let input$schema$value
const input$schema = () => (input$schema$value ??= '''+schema+''')
const $remote = createTypertRemoteInfo({package:'fixture',methods:{'fixture/echo':{
service:'fixture',invocation:{kind:'direct'},parameters:[{name:'value',source:'json',codec:{mode:'strict',typeSymbol:'Fixture',create:input$schema,jsonSchema:{type:'object'}}}],
result:{mode:'strict',typeSymbol:'Fixture',create:input$schema,jsonSchema:{type:'object'},description:'Result description'},
}}},z)
export const TYPERT={package:'fixture',face:'host',schemas:[],get invocations(){return $remote.descriptors},model:{services:[],events:[],objects:[]}}
'''


def test_generated_memo_factory_is_cached_and_strict_object_strip_modes_remain_distinct(tmp_path):
    path=tmp_path/'typert.host.js';path.write_text(generated("z.strictObject({'name':z.string().describe('Name'),'flag':z.boolean().optional()})"),encoding='utf-8')
    value=read_generated_artifact(path);validate_manifest('fixture',value)
    row=value['invocations'][0];codec=row['parameters'][0]['codec']
    assert row['id']=='fixture#fixture/echo' and row['parameters'][0]['wire']=='value'
    assert codec['create']() is codec['create']()
    assert codec['schema'].parse(dict(name='中文'))==dict(name='中文')
    with pytest.raises(ValueError):codec['schema'].parse(dict(name='x',extra=1))
    assert row['result']['schema'].to_json_schema()==dict(type='object',description='Result description')
    value=CurrentArtifactParser(generated("z.object({'name':z.string()})")).parse()
    assert value['invocations'][0]['parameters'][0]['codec']['schema'].parse(dict(name='x',extra=1))==dict(name='x')


@pytest.mark.parametrize('sample',[None,True,0,1.5,'x',[],{},dict(nested=[1,None,True])])
def test_current_json_factory_accepts_only_finite_acyclic_json(sample):
    codec=CurrentArtifactParser(generated('z.json()')).parse()['invocations'][0]['result']['schema']
    assert codec.parse(sample)==sample
    cyclic={};cyclic['self']=cyclic
    for bad in (UNDEFINED,float('inf'),float('nan'),b'bytes',object(),{1:'number key'},cyclic):
        with pytest.raises(ValueError):codec.parse(bad)


def test_generated_recursive_factories_resolve_after_declaration_without_eval():
    source=generated("z.union([z.string(),z.array(z.lazy(() => input$schema()))])")
    codec=CurrentArtifactParser(source).parse()['invocations'][0]['result']['schema']
    assert codec.parse(['x',['child']])==['x',['child']]
    with pytest.raises(ValueError):codec.parse([1])
    with pytest.raises(ValueError,match='unbound'):CurrentArtifactParser(source.replace('input$schema()', 'unknown$schema()')).parse()


@pytest.mark.parametrize('change',[
    lambda source:source.replace('z.string()', 'process.exit(0)'),
    lambda source:source.replace('input$schema$value ??=', 'other$schema$value ??='),
    lambda source:source.replace('return $remote.descriptors', 'return process.exit(0)'),
    lambda source:source.replace('createTypertRemoteInfo({', 'otherFunction({'),
    lambda source:source.replace("describe('Name')", 'transform(()=>process.exit(0))'),
    lambda source:source+'\nexport const other = 1',
])
def test_current_generated_grammar_rejects_executable_or_unowned_extensions(change):
    with pytest.raises(ValueError):CurrentArtifactParser(change(generated("z.object({'name':z.string().describe('Name')})"))).parse()


def test_missing_projection_remains_unavailable_instead_of_copying_undefined():
    codec=CodecSchema(SchemaFactory(CurrentSchema('string')),dict(jsonSchemaError='unavailable'))
    with pytest.raises(ValueError,match='unavailable'):codec.to_json_schema()
