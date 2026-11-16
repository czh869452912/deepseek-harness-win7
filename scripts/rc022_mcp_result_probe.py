"""Pair the pinned modern result decoder and dispatch validation."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_mcp_negotiation_probe import normalize


def cases():
    rows=[]
    values={'tools/list':dict(tools=[]),'tools/call':dict(content=[]),'resources/list':dict(resources=[]),
        'resources/templates/list':dict(resourceTemplates=[]),'resources/read':dict(contents=[])}
    for method,base in values.items():
        complete=dict(base,resultType='complete',ttlMs=0,cacheScope='private')
        variants=[None,[],{},dict(base),dict(complete,resultType=1),dict(complete,resultType=None),dict(complete,resultType='unknown'),
            dict(complete,resultType='input_required'),dict(complete,resultType='input_required',inputRequests=dict(x=dict(method='fixture'))),
            dict(complete,resultType='input_required',requestState='state',_meta={'custom':1}),
            dict(complete,resultType='input_required',requestState='state',_meta=1),
            complete,dict(complete,extension={'keep':True}),dict(complete,ttlMs=-1),dict(complete,ttlMs=2.5),dict(complete,cacheScope='invalid'),
            dict(complete,_meta={'custom':{'list':[1,True,None]}}),dict(complete,_meta=1)]
        for key in base:variants.extend([dict(complete,**{key:None}),dict(complete,**{key:[{}]})])
        rows.extend(dict(method=method,raw=raw) for raw in variants)
    return rows


async def observe():
    from dsh.mcp.current import RESOURCE_SCHEMAS
    from dsh.mcp.result_current import decode_modern_result
    from dsh.mcp.schemas import parse,SchemaError
    rows=[]
    for case in cases():
        decoded=decode_modern_result(case['method'],case['raw']);row=dict(decoded=decoded)
        if decoded['kind']=='complete':
            try:row['validation']=dict(ok=True,value=parse('ModernDispatch:'+case['method'],decoded['result'],RESOURCE_SCHEMAS))
            except SchemaError as error:row['validation']=dict(ok=False,reason='invalid',message=str(error))
        rows.append(normalize(row))
    return rows


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_result.mts','Actual SDK modern result decoder and dispatch validation for harness tools and resource methods, complete/input_required/unsupported variants, cache fields, schema errors and metadata projection. Full SDK caches and optional auto-fulfilment are separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/result_current.py',ROOT/'dsh/mcp/schemas.py',ROOT/'dsh/mcp/resource_schemas_current.json'],prepare=prepare)
