"""Pair the actual SDK pre-Protocol probe window and negotiation state machine."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_mcp_negotiation_probe import normalize


def cases():
    modern=dict(kind='result',result=dict(supportedVersions=['2026-07-28'],capabilities={}))
    legacy=dict(kind='rpc',error=dict(code=-32601,message='not found'))
    corrective=dict(kind='rpc',error=dict(code=-32022,message='choose another',data=dict(supported=['2026-07-28'])))
    sequences=[[modern],[legacy],[dict(kind='closed')],[dict(kind='timeout')],[dict(kind='error')],
        [corrective,modern],[corrective,corrective],[dict(kind='timeout'),modern]]
    negotiations=[dict(kind='auto',modernVersions=['2026-07-28'],fallbackAvailable=fallback,probe=dict(timeoutMs=10,maxRetries=retries))
        for fallback in (True,False) for retries in (0,1)]
    negotiations.append(dict(kind='pin',version='2026-07-28',probe=dict(timeoutMs=10)))
    rows=[dict(negotiation=n,transportKind=t,disposableProbe=d,steps=steps) for n in negotiations for t in ('stdio','http') for d in (False,True) for steps in sequences]
    rows.append(dict(negotiation=negotiations[0],transportKind='stdio',disposableProbe=True,steps=[],startError=True))
    return rows


async def observe():
    from dsh.mcp.probe_current import negotiate_era,disarm_spent_close_guard
    rows=[]
    for spec in cases():
        events=[];requests=[]
        class Transport:
            def __init__(self):
                self.starts=0;self.index=0
                self.onmessage=lambda *args:events.append('message')
                self.onerror=lambda error:events.append(['error',str(error)])
                self.onclose=lambda:events.append('close')
            async def start(self):
                self.starts+=1
                if spec.get('startError'):raise RuntimeError('start failed')
            async def send(self,packet):
                requests.append(packet);step=spec['steps'][self.index] if self.index<len(spec['steps']) else dict(kind='timeout');self.index+=1
                self.onmessage(dict(jsonrpc='2.0',method='notifications/fixture',params={}))
                self.onmessage(dict(jsonrpc='2.0',id='unrelated',result={}))
                for junk in [dict(result=None),dict(result={},extra=True),dict(error=dict(code='bad',message='bad')),dict(result={},error=dict(code=-32601,message='bad'))]:
                    self.onmessage(dict(jsonrpc='2.0',id=packet['id'],**junk))
                if step['kind']=='closed':self.onclose();return
                if step['kind']=='timeout':return
                if step['kind']=='error':
                    error=RuntimeError('send failed');self.onerror(error);raise error
                self.onmessage(dict(jsonrpc='2.0',id=packet['id'],**({'error':step['error']} if step['kind']=='rpc' else {'result':step['result']})))
        transport=Transport();saved=(transport.onmessage,transport.onerror,transport.onclose)
        try:result=await negotiate_era(spec['negotiation'],transport,transport_kind=spec['transportKind'],disposable_probe=spec['disposableProbe'],default_timeout_ms=10)
        except Exception as error:result=dict(error=normalize(error))
        restored=dict(message=transport.onmessage is saved[0],error=transport.onerror is saved[1])
        if 'error' not in result:await transport.start()
        transport.onclose();disarm_spent_close_guard(transport);transport.onclose()
        rows.append(dict(result=normalize(result),requests=requests,events=events,starts=transport.starts,restored=restored,closeRestored=transport.onclose is saved[2]))
    return rows


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_probe.mts','Actual SDK pre-Protocol probe window, raw requests/string ids, unrelated packet drop, observer restoration, close guard, one-shot start handover, retries and one corrective version. Disposable real-process ownership and application integration remain separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/probe_current.py',ROOT/'dsh/mcp/negotiation_current.py'],prepare=prepare)
