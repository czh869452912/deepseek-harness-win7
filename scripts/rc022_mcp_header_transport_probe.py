"""Actual HTTP tool parameter mirroring, filtering and mismatch recovery."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts import rc022_mcp_request_probe as peer


def cases():
    rows=[]
    for mode in ('modern-header-once','modern-header-always','modern-header-refreshbad','legacy-header-once','modern-header-schema','modern-header-compilebad'):
        rows.append(dict(mode=mode,value='中文',options=dict(timeout=1000,headers={'X-Extra':'extra','Mcp-Param-Trace':'caller','Authorization':'untrusted','Mcp-Method':'forged','Mcp-Name':'forged','Mcp-Protocol-Version':'forged','Content-Type':'forged','Accept':'application/custom'})))
    for value in ('',' ascii ','=?base64?x?=','😀',False,42,None,dict(no='header')):
        rows.append(dict(mode='modern-header-success',value=value,options={}))
    rows.append(dict(mode='modern-header-once',value='value',options=dict(toolDefinition=dict(name='probe',inputSchema=dict(properties=dict(trace={'type':'string','x-mcp-header':'Override'}))))))
    rows.append(dict(mode='modern-header-success',value='value',cursor=True,options={}))
    return rows


def selected(records,path):
    rows=[]
    for row in records:
        if row['path']!=path or row['packet']['method'] not in ('tools/list','tools/call'):continue
        headers={key:value for key,value in row['headers'].items() if key.startswith('mcp-') or key in ('authorization','content-type','x-extra','accept')}
        rows.append(dict(packet=row['packet'],headers=headers))
    return rows


async def observe():
    from dsh.mcp.client_current import CurrentSdkClient
    from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport
    output=[]
    for index,case in enumerate(cases()):
        path='/native/header/'+str(index)+'/'+case['mode'];client=CurrentSdkClient();wire=CurrentStreamableHttpMcpTransport(peer.URL+path,dict(Authorization='Bearer owned'))
        errors=[];client.onerror=lambda error:errors.append(dict(name=getattr(error,'name','Error'),message=str(error),code=getattr(error,'code',None)))
        try:
            await client.connect(wire)
            listing=await client.listTools(dict(cursor='explicit') if case.get('cursor') else None)
            try:result=dict(value=await client.callTool(dict(name='probe',arguments=dict(trace=case['value'])),case['options']))
            except Exception as error:
                item=dict(name=getattr(error,'name','Error'),message=str(error))
                for key in ('code','data'):
                    if hasattr(error,key):item[key]=getattr(error,key)
                result=dict(error=item)
        finally:await client.close()
        output.append(dict(case=case,tools=[tool['name'] for tool in listing['tools']],result=result,errors=errors,wire=selected(peer.records(),path)))
    return output


def prepare(output):
    inputs=peer.prepare(output);path=inputs[0];data=json.loads(path.read_text(encoding='utf-8'));data['cases']=cases();path.write_text(json.dumps(data),encoding='utf-8');return inputs


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_mcp_header_transport.mts','Actual auto-negotiated modern/legacy HTTP: invalid declaration filtering, exact parameter/header values, protected request headers, original credential ownership, list cache/explicit cursor, one HEADER_MISMATCH evict/refresh/recompile/retry, refresh failure and no override retry.',extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/mcp/client_current.py',ROOT/'dsh/mcp/http_current.py',ROOT/'scripts/oracles/rc022_mcp_request_peer.py'],prepare=prepare)
    finally:peer.stop_peer()
