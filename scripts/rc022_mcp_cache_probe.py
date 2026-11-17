"""Compare actual SDK cache methods against identical scripted request collaborators."""
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    def action(verb, **extra):return dict(verb=verb,**extra)
    rows=[]
    for verb in ('listTools','listResources','listResourceTemplates','readResource'):
        rows.append(dict(name=verb,actions=[action(verb),action('mutate'),action(verb),
            action(verb,options=dict(cacheMode='bypass')),action(verb),
            action(verb,options=dict(cacheMode='refresh')),action(verb),
            action('advance',ms=100),action(verb)]))
    rows.extend([
        dict(name='zero-ttl',ttl=0,actions=[action('listTools'),action('listTools'),action('readResource'),action('readResource')]),
        dict(name='default-ttl',ttl='not-a-number',defaultTtl=20,actions=[action('listResources'),action('advance',ms=19),action('listResources'),action('advance',ms=1),action('listResources')]),
        dict(name='clamped-ttl',ttl=100000000,actions=[action('listTools'),action('advance',ms=86399999),action('listTools'),action('advance',ms=1),action('listTools')]),
        dict(name='lists-invalidated',actions=[action('listTools'),action('listResources'),action('listResourceTemplates'),action('notify',method='notifications/resources/list_changed'),action('listResources'),action('listResourceTemplates'),action('listTools'),action('notify',method='notifications/tools/list_changed'),action('listTools')]),
        dict(name='uri-invalidated',actions=[action('readResource'),action('readResource',params=dict(uri='doc://b')),action('notify',method='notifications/resources/updated',params=dict(uri='doc://a')),action('readResource'),action('readResource',params=dict(uri='doc://b'))]),
        dict(name='pagination-meta',pages=3,actions=[action('listTools',params=dict(_meta=dict(trace='owned'))),action('listTools'),action('listTools',params=dict(cursor='1'))]),
        dict(name='list-in-flight-invalidation',pages=3,invalidateAt=2,notification=dict(method='notifications/tools/list_changed'),actions=[action('listTools'),action('listTools'),action('listTools')]),
        dict(name='read-in-flight-invalidation',invalidateAt=1,notification=dict(method='notifications/resources/updated',params=dict(uri='doc://a')),actions=[action('readResource'),action('readResource'),action('readResource')]),
        dict(name='pagination-failure',pages=3,failAt=2,actions=[action('listTools'),action('listTools'),action('listTools')]),
        dict(name='pagination-limit',pages=3,maxPages=2,actions=[action('listTools'),action('listTools')]),
        dict(name='pagination-unlimited',pages=3,maxPages=0,actions=[action('listTools'),action('listTools')]),
        dict(name='zero-refresh-evicts-read',actions=[action('readResource'),action('setTtl',value=0),action('readResource',options=dict(cacheMode='refresh')),action('readResource'),action('listTools'),action('listTools')]),
    ])
    return rows


async def observe():
    from dsh.mcp.client_current import CurrentSdkClient
    from dsh.cordis.json_text import stringify_json
    output=[]
    for case in cases():
        client=CurrentSdkClient(default_cache_ttl_ms=case.get('defaultTtl',0),list_max_pages=case.get('maxPages',64))
        clock=[0];client._cache.now=lambda:clock[0]
        state=dict(ttl=case.get('ttl',100),count=0);requests=[];rows=[];last=None
        def notify(packet):client._notification(packet)
        async def request(packet,options=None):
            requests.append(json.loads(stringify_json(packet)));state['count']+=1;count=state['count']
            if count==case.get('invalidateAt'):notify(case['notification'])
            if count==case.get('failAt'):raise RuntimeError('scripted page failure')
            method=packet['method'];params=packet.get('params') or {};page=int(params.get('cursor','0'))
            result=dict(ttlMs=state['ttl'],cacheScope='private')
            if method=='resources/read':result['contents']=[dict(uri=params['uri'],text=str(count))]
            else:
                key={'tools/list':'tools','resources/list':'resources','resources/templates/list':'resourceTemplates'}[method]
                item=dict(name='item'+str(count))
                if key=='tools':item['inputSchema']=dict(type='object')
                elif key=='resources':item['uri']='doc://'+str(count)
                else:item['uriTemplate']='doc://{'+str(count)+'}'
                result[key]=[item]
                if page+1<case.get('pages',1):result['nextCursor']=str(page+1)
            return result
        client.request=request
        for entry in case['actions']:
            verb=entry['verb']
            if verb=='advance':clock[0]+=entry['ms'];continue
            if verb=='setTtl':state['ttl']=entry['value'];continue
            if verb=='notify':notify({k:v for k,v in entry.items() if k!='verb'});continue
            if verb=='mutate':
                last['ttlMs']=-1
                key=next(key for key in ('tools','resources','resourceTemplates','contents') if key in last)
                last[key][0]['name']='mutated';continue
            params=entry.get('params',dict(uri='doc://a') if verb=='readResource' else None)
            try:
                last=await getattr(client,verb)(params,entry.get('options'));rows.append(dict(value=json.loads(stringify_json(last))))
            except Exception as error:
                row=dict(name=getattr(error,'name','Error'),message=str(error))
                for key in ('code','data'):
                    if getattr(error,key,None) is not None:row[key]=getattr(error,key)
                rows.append(dict(error=row))
        output.append(dict(name=case['name'],rows=rows,requests=requests))
    return output


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_cache.mts','Actual default SDK response cache methods with scripted request collaborators: TTL and boundaries, refresh/bypass, mutation barriers, pagination metadata, notification generations and failed aggregates. No custom shared store or wire acceptance claimed.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/mcp/client_current.py',ROOT/'dsh/mcp/response_cache_current.py'],prepare=prepare)
