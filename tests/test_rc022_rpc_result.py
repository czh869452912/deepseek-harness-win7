import pytest
from dsh.typert.rpc_result import encode_rpc_result, json_projection
from scripts.rc022_rpc_result_probe import observe


@pytest.mark.asyncio
async def test_actual_rpc_result_materialization_and_binary_paths():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==16
    assert rows['root-bytes']['result']==dict(ok=True,value=None,attachments=[dict(path=[],bytes=[97,98,99])])
    attachments=rows['nested-bytes']['result']['attachments']
    assert [item['path'] for item in attachments]==[['a.b/c',0],['a.b/c',1,'data'],['__proto__','data']]
    assert attachments[0]['bytes']==[49,50,51]
    assert rows['undefined']['result']==dict(ok=True)
    assert rows['function']['result']==dict(ok=True)
    assert rows['json-omissions']['result']['value']==dict(array=[None,None,None,None])
    assert rows['cycle']['result']==dict(ok=False,error=dict(code='gateway/internal',message='gateway: circular RPC result',details={}))
    assert rows['to-json-bytes']['calls']==['nested']
    assert rows['getter']['calls']==['data']
    assert rows['date']['result']['value']=='2026-01-02T03:04:05.006Z'
    assert [item['path'] for item in rows['numeric-keys']['result']['attachments']]==[['2'],['10'],['x']]


def test_rpc_attachment_views_and_paths_keep_their_contract():
    data=bytearray(b'01234');view=memoryview(data)[1:4]
    result=encode_rpc_result(dict(data=view),dict(mode='src-json'))
    assert result['attachments'][0]['bytes'] is view
    data[2]=ord('X')
    assert bytes(result['attachments'][0]['bytes'])==b'1X3'
    original_path=['payload']
    def encode(value,write):
        value=write(data,original_path);original_path.append('later');return dict(bytes=value)
    result=encode_rpc_result(None,dict(mode='strict',encode=encode))
    assert result['attachments'][0]['path']==['payload']


@pytest.mark.parametrize('value',[False,0,''])
def test_strict_encoder_preserves_false_zero_and_empty_string(value):
    result=encode_rpc_result(dict(original=True),dict(mode='strict',encode=lambda *_:value))
    assert result['value'] is value


def test_strict_output_encoder_does_not_run_input_schema():
    class InputSchema:
        def parse(self,value):raise AssertionError('result parsing is not part of RPC encoding')
    assert encode_rpc_result(dict(value='raw'),dict(mode='strict',schema=InputSchema()))==dict(ok=True,value=dict(value='raw'))
