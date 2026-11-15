import pytest
from dsh.host.connection.rpc_current import full_response
from scripts.rc022_rpc_http_probe import decode_response,observe


@pytest.mark.asyncio
async def test_gateway_to_http_binary_and_validation_boundaries():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==16
    assert rows['root-bytes']['response']['parts'][0]['bytes']==[0,128,255]
    nested=rows['nested-bytes']['response']
    assert [item['path'] for item in nested['metadata']['attachments']]==[['a.b/c',0],['a.b/c',1,'data']]
    assert nested['parts'][0]['bytes']==[49,50,51]
    assert rows['empty-bytes']['response']['parts'][0]['bytes']==[]
    assert rows['undefined']['response']['body']['result']==dict(ok=True)
    assert rows['null']['response']['body']['result']==dict(ok=True,value=None)
    assert rows['peer']['response']['body']['result']['value']==dict(kind='owner')
    for name in ('bad-json','bad-media','bad-method','mismatch','missing-payload','bad-envelope'):
        assert rows[name]['seen']==[]
    assert rows['throws']['response']['body']=='handler failure: Error: boom'


def test_multipart_copies_views_and_preserves_arbitrary_binary_delimiters():
    data=bytearray(bytes(range(256))+b'\r\n--not-a-boundary\r\n')
    result=full_response('id',dict(ok=True,value=dict(data=None),attachments=[dict(path=['data'],bytes=memoryview(data)[1:])]))
    expected=list(data[1:]);data[:]=b'x'*len(data)
    decoded=decode_response(result)
    assert decoded['parts'][0]['bytes']==expected
    assert decoded['metadata']['attachments']==[dict(path=['data'],codec='bytes',part='bytes-0')]
