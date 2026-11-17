"""Actual SDK HTTP/SSE request timers, serving errors and abort ownership."""
import asyncio,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
PEER=None;URL=None;LOG=None


def cases():
    rows=[]
    for era in ('legacy','modern'):
        rows.extend(dict(mode=era+'-'+mode,options=options) for mode,options in [
            ('hold',dict(timeout=50)),('progress',dict(timeout=180,onprogress=True)),
            ('progress',dict(timeout=180,onprogress=True,resetTimeoutOnProgress=True)),
            ('progress',dict(timeout=180,onprogress=True,resetTimeoutOnProgress=True,maxTotalTimeout=250)),
            ('complete',dict(timeout=500,maxTotalTimeout=1)),
            ('error',{}),('error-null',{}),('error-object',{})])
        rows.extend(dict(mode=era+'-hold',options=dict(timeout=2000),abort=reason,pre=pre)
            for reason in ('text','null','object','error','sdk','zero','false','array') for pre in (False,True))
        rows.append(dict(mode=era+'-hold',options=dict(timeout=2000),disconnect=True))
    return rows


def records():return [json.loads(line) for line in LOG.read_text(encoding='utf-8').splitlines()] if LOG.exists() else []


async def observe():
    from dsh.core.abort import AbortController
    from dsh.mcp.client_current import CurrentSdkClient
    from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport
    from dsh.mcp.negotiation_current import SdkError
    from dsh.mcp.diagnostic_current import CurrentProtocolError
    import dsh.mcp.request_current as timers
    output=[];previous=timers.now_ms
    try:
        for index,case in enumerate(cases()):
            path='/native/'+str(index)+'/'+case['mode'];client=CurrentSdkClient();wire=CurrentStreamableHttpMcpTransport(URL+path)
            controller=AbortController();progress=[];clock=[0];timers.now_ms=lambda:clock[0]
            reason={'text':'stop','null':None,'object':dict(stop=True),'error':RuntimeError('stop'),'sdk':SdkError('OWNED_ABORT','stop',dict(owned=True)),'zero':0,'false':False,'array':['a',2]}.get(case.get('abort'))
            result=None;elapsed=None
            try:
                await client.connect(wire)
                original=wire._receive
                async def receive(packet):
                    if packet.get('method')=='notifications/progress' and getattr(wire,'_sdk_requests',{}):clock[0]=100*packet['params']['progress']
                    return await original(packet)
                wire._receive=receive
                options=dict(case['options'],signal=controller.signal)
                if options.get('onprogress'):options['onprogress']=progress.append
                if case.get('pre'):controller.abort(reason)
                pending=asyncio.create_task(client.listTools(options=options))
                if ('abort' in case and not case.get('pre')) or case.get('disconnect'):
                    for _ in range(1000):
                        if any(row['path']==path and row['packet']['method']=='tools/list' for row in records()):break
                        await asyncio.sleep(.002)
                    else:raise AssertionError('serving request not observed')
                    if case.get('disconnect'):await client.close()
                    else:controller.abort(reason)
                try:result=dict(value=await pending)
                except Exception as error:
                    value=dict(name=getattr(error,'name','Error'),message=str(error))
                    for key in ('code','data'):
                        if hasattr(error,key) and (getattr(error,key) is not None or isinstance(error,CurrentProtocolError)):
                            value[key]=getattr(error,key)
                    result=dict(error=value,reasonIdentity=error is reason)
                if 'abort' in case or case['mode'].endswith('hold') or (case['options'].get('onprogress') and not case['options'].get('resetTimeoutOnProgress')):
                    await asyncio.sleep(.03)
                elapsed=clock[0]
                assert not wire._pending and not getattr(wire,'_sdk_requests',{})
            finally:
                await client.close()
                assert not wire._writers
            packets=[row['packet'] for row in records() if row['path']==path and row['packet']['method'] in ('tools/list','notifications/cancelled')]
            output.append(dict(case=case,result=result,progress=progress,elapsed=elapsed,packets=packets,listeners=len(controller.signal._listeners)))
    finally:timers.now_ms=previous
    return output


def prepare(output):
    global PEER,URL,LOG
    LOG=output/'http-peer.jsonl'
    PEER=subprocess.Popen([sys.executable,str(ROOT/'scripts/oracles/rc022_mcp_request_peer.py'),str(LOG)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    URL=PEER.stdout.readline().decode().strip();assert URL.startswith('http://127.0.0.1:')
    path=output/'input.json';path.write_text(json.dumps(dict(url=URL,log=str(LOG),cases=cases())),encoding='utf-8');return [path]


def stop_peer():
    global PEER
    if PEER is not None:
        try:PEER.communicate(timeout=5)
        except subprocess.TimeoutExpired:PEER.kill();PEER.communicate()
        PEER=None


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_mcp_request.mts','Actual SDK and Native HTTP/SSE: per-leg timeout, progress reset/total limit, serving ProtocolError data, pre/in-flight arbitrary abort reasons, modern request-stream versus legacy cancellation notification, pending/socket/listener cleanup. Timer start/progress timestamps use the same controlled clock while actual network and timer delays execute.',extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/mcp/request_current.py',ROOT/'dsh/mcp/http_current.py',ROOT/'scripts/oracles/rc022_mcp_request_peer.py'],prepare=prepare)
    finally:stop_peer()
