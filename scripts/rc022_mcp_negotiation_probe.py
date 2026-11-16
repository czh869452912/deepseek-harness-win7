"""Pair pinned SDK 2 probe outcome decisions, including schema projection."""
import copy
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    contexts=[dict(clientModernVersions=['2026-07-28'],requestedVersion='2026-07-28',fallbackAvailable=fallback,
        environment=environment,transportKind=transport) for fallback in (True,False) for environment in ('node','browser') for transport in ('stdio','http')]
    results=[None,{},dict(supportedVersions=['2026-07-28'],capabilities={}),
        dict(supportedVersions=['2025-11-25'],capabilities={}),dict(supportedVersions=[],capabilities={}),
        dict(supportedVersions=['2026-07-28'],capabilities={},ttlMs=-1,cacheScope='broken',resultType='complete',extra=1),
        dict(supportedVersions=['2026-07-28'],capabilities={},ttlMs=2.5,cacheScope='public',instructions='literal {{model}}',_meta={'custom':{'list':[None,True,2,'x']}}),
        dict(supportedVersions=['2026-07-28'],capabilities={},resultType='invalid'),
        dict(supportedVersions=['2026-07-28'],capabilities={'tools':{'listChanged':True},'experimental':{'x':{}}}),
        dict(supportedVersions=['2026-07-28'],capabilities={},ttlMs=9007199254740992),
        dict(supportedVersions=[1],capabilities={}),dict(supportedVersions=['2026-07-28'],capabilities=None)]
    outcomes=[dict(kind='result',result=result) for result in results]
    for supported in (None,[],['2025-11-25'],['2026-07-28'],['2027-01-01'],['garbage'],[1],['2026-07-28','2025-11-25']):
        for requested in (None,'2026-other'):
            outcomes.append(dict(kind='rpc-error',code=-32022,message='server version error',data=dict(supported=supported,requested=requested)))
    outcomes.extend(dict(kind='rpc-error',code=code,message='unrecognized',data={}) for code in (-32601,-32600,-32602,-32000,0))
    for status in (200,400,401,403,404,405,422,429,500,503):
        for body in ('', 'invalid',json.dumps(dict(error=dict(code=-32022,message='wrong version',data=dict(supported=['2026-07-28'])))),json.dumps(dict(error=dict(code=-32022,data=dict(supported=['2025-11-25']))))):
            outcomes.append(dict(kind='http-error',status=status,statusText='fixture',body=body))
    outcomes.extend([dict(kind='closed'),dict(kind='timeout',timeoutMs=37)])
    for kind in ('network-error','auth-required'):
        for name in ('Error','TypeError','CustomError'):
            outcomes.append(dict(kind=kind,error=dict(fixtureError=True,name=name,message='fixture failure')))
    return [dict(outcome=copy.deepcopy(outcome),context=context) for context in contexts for outcome in outcomes]


def normalize(value):
    if isinstance(value,BaseException):
        result=dict(name=getattr(value,'name','TypeError' if isinstance(value,TypeError) else 'Error'),message=str(value))
        if hasattr(value,'code'):result['code']=value.code
        if getattr(value,'data',None) is not None:result['data']=normalize(value.data)
        return result
    if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
    if isinstance(value,list):return [normalize(item) for item in value]
    return value


async def observe():
    from dsh.mcp.negotiation_current import classify_probe_outcome
    rows=[]
    for row in cases():
        outcome=row['outcome']
        if isinstance(outcome.get('error'),dict) and outcome['error'].get('fixtureError'):
            spec=outcome['error'];error=TypeError(spec['message']) if spec['name']=='TypeError' else RuntimeError(spec['message']);error.name=spec['name'];outcome['error']=error
        rows.append(normalize(classify_probe_outcome(outcome,row['context'])))
    return rows


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_negotiation.mts','Pinned SDK 2 actual private classifier versus Python: discover schema/default/catch projection, corrective versions, legacy eligibility, HTTP, network/auth, timeout and close decisions. Transport lifecycle remains separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/negotiation_current.py',ROOT/'dsh/mcp/schemas.py',ROOT/'dsh/mcp/resource_schemas_current.json'],prepare=prepare)
