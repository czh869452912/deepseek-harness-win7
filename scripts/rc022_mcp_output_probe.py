"""Actual SDK callTool schema/cache semantics with scripted request collaborators."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    schemas=[{},dict(type='object',properties=dict(x=dict(type='number')),required=['x'],additionalProperties=False),
        dict(type='object',properties=dict(x=dict(type='string',format='email'))),
        dict(type='object',properties=dict(x=dict(type='string',minLength=2,pattern='^[a-z]+$'))),
        dict(type='object',properties=dict(x=dict(type='integer',minimum=1,maximum=4,multipleOf=2))),
        dict(type='object',properties=dict(x=dict(enum=['a',1,None]))),
        dict(type='object',properties=dict(x=dict(oneOf=[dict(type='number'),dict(type='integer')]))),
        dict(type='object',properties=dict(x=dict(type='array',items=dict(type='number'),minItems=2,uniqueItems=True))),
        {'type':'object','$defs':{'item':{'type':'string'}},'properties':{'x':{'$ref':'#/$defs/item'}}},
        {'$schema':'http://json-schema.org/draft-07/schema#','type':'object','dependencies':{'x':['y']}},
        {'$schema':'https://json-schema.org/draft/2019-09/schema','type':'object','dependentRequired':{'x':['y']}},
        {'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','unevaluatedProperties':False},
        {'$schema':'https://invalid.example/schema','type':'object'},
        {'type':'object','properties':{'x':{'$ref':'#/$defs/missing'}}},
        {'type':'object','properties':{'x':{'type':'string','pattern':'['}}}]
    values=[{},dict(x=2),dict(x='a'),dict(x='test@example.com'),dict(x=[1,1]),dict(x=[1,2]),dict(x=None)]
    rows=[dict(name='schema-'+str(i),schema=schema,actions=[dict(result=dict(content=[],structuredContent=value)) for value in values]+[
        dict(result=dict(content=[])),dict(result=dict(content=[],isError=True)),dict(result=dict(content=[],isError=True,structuredContent=dict(x='invalid')))]) for i,schema in enumerate(schemas)]
    rows.extend([
        dict(name='unlisted',actions=[dict(result=dict(content=[],structuredContent=dict(x='bad')))]),
        dict(name='notify-drops-schema',schema=schemas[1],actions=[dict(notify=True),dict(result=dict(content=[]))]),
        dict(name='override-isolated',schema=schemas[1],actions=[dict(override=dict(type='object'),result=dict(content=[],structuredContent=dict(x='bad'))),dict(result=dict(content=[],structuredContent=dict(x='bad')))]),
        dict(name='provider-id-retained',actions=[dict(override={'$id':'https://example.test/owned','type':'object','properties':{'x':{'type':'number'}}},result=dict(content=[],structuredContent=dict(x=1))),dict(override={'$id':'https://example.test/owned','type':'object','properties':{'x':{'type':'string'}}},result=dict(content=[],structuredContent=dict(x=1)))]),
        dict(name='error-isolation',schema=schemas[12],actions=[dict(tool='good',result=dict(content=[],structuredContent=dict(x='anything'))),dict(result=dict(content=[]))]),
    ])
    return rows


async def observe():
    from dsh.mcp.client_current import CurrentSdkClient
    output=[]
    for case in cases():
        client=CurrentSdkClient();requests=[];rows=[];current=[None]
        async def request(packet,options=None):
            requests.append(packet)
            if packet['method']=='tools/list':return dict(tools=[dict(name='probe',inputSchema=dict(type='object'),outputSchema=case['schema']),dict(name='good',inputSchema=dict(type='object'),outputSchema={})])
            return current[0]
        client.request=request
        try:
            if 'schema' in case:await client.listTools()
            for action in case['actions']:
                if action.get('notify'):
                    client._notification(dict(method='notifications/tools/list_changed'));continue
                current[0]=action['result'];options=dict(toolDefinition=dict(name='probe',inputSchema=dict(type='object'),outputSchema=action['override'])) if 'override' in action else None
                try:rows.append(dict(value=await client.callTool(dict(name=action.get('tool','probe')),options)))
                except Exception as error:
                    row=dict(name=getattr(error,'name','Error'),message=str(error))
                    for key in ('code','data'):
                        if getattr(error,key,None) is not None:row[key]=getattr(error,key)
                    rows.append(dict(error=row))
        finally:await client.close()
        output.append(dict(name=case['name'],rows=rows,requests=requests))
    return output


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_output.mts','Actual Client callTool output schema validation and cache ownership with scripted request collaborators: drafts, references, formats, invalid schemas, error results, override isolation, retained provider ids and list notification eviction.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/mcp/client_current.py',ROOT/'dsh/mcp/output_validator_current.py',ROOT/'dsh/mcp/validator/manifest.json'],prepare=prepare)
