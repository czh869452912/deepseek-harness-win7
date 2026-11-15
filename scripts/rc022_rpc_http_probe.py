"""Pair the actual upstream Connection HTTP adapter with the candidate carrier."""
import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CASES=['plain','root-bytes','nested-bytes','empty-bytes','undefined','null','failure','empty-attachments','bad-json','bad-media','bad-method','mismatch','missing-payload','bad-envelope','throws','peer']


def decode_response(result):
    media=result['headers'].get('content-type','').split(';')[0]
    body=result['body']
    if media=='multipart/form-data':
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+result['headers']['content-type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
        parts=[];metadata=None
        for part in message.iter_parts():
            name=part.get_param('name',header='content-disposition');data=part.get_payload(decode=True)
            if name=='metadata':metadata=json.loads(data)
            else:parts.append(dict(name=name,filename=part.get_filename(),type=part.get_content_type(),bytes=list(data)))
        return dict(status=result['status'],media=media,metadata=metadata,parts=parts)
    return dict(status=result['status'],media='json' if media=='application/json' else 'text',body=json.loads(body) if media=='application/json' else body)


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.session.json import UNDEFINED
    from dsh.host.connection.peer import Peer
    from dsh.host.connection.rpc_current import rpc_fetch_handler
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import Remote,TypertRemoteService
    rows=[]
    for name in CASES:
        ctx=Context();await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService);await ctx.plugin(AuthorizedGatewayCore)
        class Fixture(TypertRemoteService):
            def __init__(self,child):super().__init__(child,'fixture')
            @Remote
            def value(self):
                return {'plain':dict(text='中文'), 'root-bytes':b'\x00\x80\xff', 'nested-bytes':{'a.b/c':[memoryview(b'01234')[1:4],dict(data=b'xy')]}, 'empty-bytes':b'', 'undefined':UNDEFINED,'null':None}.get(name)
        try:
            await ctx.plugin(Fixture);peer=Peer(ctx,dict(principal=dict(kind='owner')));seen=[]
            async def handler(endpoint,payload,signal,trusted):
                seen.append(dict(endpoint=endpoint,peer=trusted is peer,signal=signal is NEVER_ABORTED,payload=payload))
                if name=='throws':raise RuntimeError('boom')
                if name=='failure':return dict(ok=False,error=dict(code='fixture/no',message='no',details={}))
                if name=='empty-attachments':return dict(ok=True,value=2,attachments=[])
                if name=='peer':return dict(ok=True,value=trusted.principal)
                return await ctx.typertGateway.invoke_rpc(endpoint,payload,signal,trusted)
            body=dict(type='client-request',rpcId='request',method='fixture/value',payload=dict(args={}))
            if name=='peer':body['payload']['peer']=dict(principal=dict(kind='forged'))
            if name=='mismatch':body['method']='other/run'
            if name=='missing-payload':body.pop('payload')
            if name=='bad-envelope':body=dict(rpcId='known')
            request=dict(path='/api/fixture/value',method='GET' if name=='bad-method' else 'POST',headers={'content-type':'text/plain' if name=='bad-media' else 'Application/JSON; charset=utf-8'},body=b'{' if name=='bad-json' else json.dumps(body).encode(),signal=NEVER_ABORTED)
            result=await rpc_fetch_handler('/api',handler).fetch(request,peer)
            rows.append(dict(name=name,response=decode_response(result),seen=seen))
        finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_rpc_http.mts','Actual upstream shared Connection Fetch adapter versus candidate Peer-aware HTTP adapter, including actual Gateway result extraction and multipart parsing. Network admission remains separate.',[Path(__file__).resolve(),ROOT/'dsh/host/connection/rpc_current.py',ROOT/'dsh/host/connection/rpc_host.py'])
