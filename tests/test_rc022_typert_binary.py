import os
from pathlib import Path

import pytest

from dsh.typert.artifact import UNDEFINED,read_generated_artifact
from dsh.typert.artifact_binary import PROGRAM,encode_selected_data
from dsh.typert.artifact_current import CurrentArtifactParser
from dsh.typert.loader import validate_manifest
from dsh.typert.rpc_result import encode_rpc_result
from test_rc022_typert_artifact import PREFIX


def generated():
    return PREFIX+PROGRAM+'''let result$schema$value
const result$schema = () => (result$schema$value ??= z.object({'data':z.instanceof(Uint8Array)}))
const $remote=createTypertRemoteInfo({package:'fixture',methods:{'fixture/read':{
service:'fixture',invocation:{kind:'direct'},parameters:[],result:{mode:'strict',typeSymbol:'Bytes',create:result$schema,
jsonSchemaError:'bytes unavailable',decode:value => result$schema().parse(value),encode:(value, writeBytes) => $encode0(value, writeBytes, [], new Map())}
}}},z)
export const TYPERT={package:'fixture',face:'host',schemas:[],get invocations(){return $remote.descriptors},model:{services:[],events:[],objects:[]}}
'''


@pytest.mark.parametrize('data',[b'',b'\x00\xff',bytearray(b'ab'),memoryview(b'0123')[1:3]])
def test_generated_binary_result_attaches_only_declared_data_and_preserves_view(data):
    artifact=CurrentArtifactParser(generated()).parse();validate_manifest('fixture',artifact)
    codec=artifact['invocations'][0]['result'];original=dict(data=data,extra=b'raw')
    result=encode_rpc_result(original,codec)
    assert result['value']==dict(data=None,extra=b'raw')
    assert result['attachments']==[dict(path=['data'],bytes=data)]
    assert result['attachments'][0]['bytes'] is data and original['data'] is data
    assert codec['decode'](original)==dict(data=data)
    with pytest.raises(ValueError):codec['decode'](dict(data=[1,2]))
    with pytest.raises(ValueError):codec['schema'].to_json_schema()


@pytest.mark.parametrize('before,after',[
    ("'data')) value['data']", "'extra')) value['data']"),
    ('writeBytes(value, path)', 'writeBytes(value, [])'),
    ('snapshot ? $resultSnapshot(input, path) : input','input'),
    ('value => result$schema().parse(value)','value => result$schema().parse(null)'),
    ('$encode0(value, writeBytes, [], new Map())','$encode1(value, writeBytes, [], new Map())'),
    ('z.instanceof(Uint8Array)','z.instanceof(Buffer)'),
])
def test_unqualified_generated_program_or_inline_function_is_refused(before,after):
    source=generated();assert before in source
    with pytest.raises(ValueError):CurrentArtifactParser(source.replace(before,after)).parse()


def test_byte_functions_require_the_qualified_program_and_snapshot_once():
    with pytest.raises(ValueError):CurrentArtifactParser(generated().replace(PROGRAM,'')).parse()
    calls=[];original=dict(data=b'abc')
    def snapshot(key):calls.append(key);return original
    original['toJSON']=snapshot
    result=encode_selected_data(original,lambda value,path: dict(path=path,size=len(value)))
    assert calls==['value'] and result==dict(data=dict(path=['data'],size=3))
    assert original['data']==b'abc' and original['toJSON'] is snapshot
    assert encode_selected_data(UNDEFINED,lambda *_:None) is UNDEFINED


SOURCE=Path(os.environ.get('DSH_RC022_SOURCE',str(Path(__file__).resolve().parents[1]/'reference')))


@pytest.mark.parametrize('package',['api/workspace-files','document/office-kit'])
def test_actual_original_generated_byte_result_encodes_without_input_validation(package):
    path=SOURCE/('packages/'+package+'/lib/typert.host.js')
    if not path.is_file():pytest.skip('actual pinned generated artifact required')
    artifact=read_generated_artifact(path);validate_manifest(artifact['package'],artifact)
    codec=next(row['result'] for row in artifact['invocations'] if 'encode' in row['result'])
    result=encode_rpc_result(dict(data=b'abc'),codec)
    assert result==dict(ok=True,value=dict(data=None),attachments=[dict(path=['data'],bytes=b'abc')])
    with pytest.raises(ValueError):codec['decode'](dict(data=b'abc'))
