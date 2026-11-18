"""Pair config references, schema validation and raw comparison with fixed Source."""
import datetime
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.cordis import Schema as z
from dsh.cordis.utils import _UNDEFINED, deep_equal
from dsh.cordis.volatile import create_volatile,is_volatile,volatile_entries
from dsh.cordis.loader_diff import equal_except_volatile


class Opaque:
    def __init__(self):self.value=1


def decode(value):
    if isinstance(value,dict) and '$type' in value:
        tag=value['$type']
        if tag=='undefined':return _UNDEFINED
        if tag=='ref':return create_volatile(decode(value['value']))
        if tag=='cycle':
            result={};result['self']=result;return result
        if tag=='opaque':return Opaque()
        if tag=='date':return datetime.datetime(1970,1,1)+datetime.timedelta(milliseconds=value['value'])
        if tag=='function':return lambda:1
    if isinstance(value,dict):return {key:decode(item) for key,item in value.items()}
    if isinstance(value,list):return [decode(item) for item in value]
    return value


def normalize(value):
    if value is _UNDEFINED:return {'$type':'undefined'}
    if is_volatile(value):return {'$type':'ref','value':normalize(value.get())}
    if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
    if isinstance(value,list):return [normalize(item) for item in value]
    return value


def schema(name):
    def live():return z.string().volatile()
    if name=='config':return z.object({'fixed':z.string().default('fixed'),'title':z.string().default('hello').volatile(),'optional':live(),'nested':z.object({'count':z.number().min(0).volatile().default(1)}).default({}),'group':z.object({'list':z.array(z.string())}).default({'list':[]}).volatile()})
    if name=='scalar':return live().default('hello')
    if name=='array':return z.array(z.string()).volatile()
    if name=='union':return z.union([z.string(),z.number()]).volatile()
    if name=='date':return z.object({'block':z.object({'when':z.date().volatile()})})
    if name=='bad-array':return z.object({'items':z.array(live())})
    if name=='bad-dict':return z.object({'items':z.dict(live())})
    if name=='bad-union':return z.union([z.object({'title':live()}),z.string()])
    if name=='bad-tuple':return z.object({'items':z.tuple([live()])})
    if name=='bad-intersect':return z.intersect([z.object({'title':live()})])
    if name=='bad-transform':return z.transform(z.object({'title':live()}),lambda value:value)
    if name=='bad-nested':return z.object({'block':z.object({'title':live()}).volatile()})
    if name=='bad-lazy':return z.object({'lazy':z.lazy(lambda:z.object({'live':live()}))})
    if name=='metadata-free':return z({'type':'object','dict':{'enabled':{'type':'boolean'}}})
    if name=='raw-nested':return z.object({'nested':z.object({'live':live(),'fixed':z.string()}).default({'fixed':'default'})})
    if name=='raw-shared':
        shared=z.object({'value':live()});return z.object({'first':shared,'second':shared})
    if name=='raw-recursive':
        recursive=z.object({'value':z.string()}).extra('default',_UNDEFINED);recursive.set('child',recursive);return recursive
    return None


def cases():
    values=[{'$type':'undefined'},None,False,0,1,'text',{},[],[None],[{'$type':'undefined'}],{'x':None},{'$type':'ref','value':1},{'$type':'ref','value':2},{'$type':'cycle'},{'$type':'opaque'},{'$type':'date','value':0},{'$type':'date','value':1}]
    result=[dict(op='deep',left=left,right=right,strict=strict) for left in values for right in values for strict in (False,True)]
    for name in ('config','scalar','array','union','date','bad-array','bad-dict','bad-union','bad-tuple','bad-intersect','bad-transform','bad-nested','bad-lazy','metadata-free'):
        data=[{},None,{'$type':'undefined'}]
        if name=='config':data += [{'title':'new'},{'nested':{'count':-1}},{'group':{'list':['a']}}]
        if name in ('scalar','union'):data += ['text',1,False]
        if name=='array':data += [['a'],[1]]
        if name=='date':data += [{'block':{'when':{'$type':'date','value':0}}}]
        if name=='bad-lazy':data += [{'lazy':{'live':'new'}}]
        if name=='metadata-free':data += [{'enabled':True},{'enabled':'no'}]
        for value in data:result.append(dict(op='schema',schema=name,data=value))
    result.append(dict(op='schema',schema='config',data={'nested':{'count':-1}},options={'autofix':True}))
    for value in values:result.append(dict(op='snapshot',data=value))
    raw=[{},None,{'$type':'undefined'},{'title':'new'},{'title':{'__jsExpr':'throw 1'}},{'fixed':'changed'},{'nested':{'live':'new','fixed':'default'}},{'nested':{'live':'new'}},{'nested':{'__jsExpr':1}},{'unknown':1}]
    for name in ('config','raw-nested','raw-shared','raw-recursive','none'):
        for left in raw:
            for right in raw:result.append(dict(op='diff',schema=name,left=left,right=right))
    return result


CORPUS=cases()


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(CORPUS,ensure_ascii=False),encoding='utf-8');return [path]


async def native():
    results=[]
    for row in CORPUS:
        try:
            if row['op']=='deep':value=deep_equal(decode(row['left']),decode(row['right']),row['strict'])
            elif row['op']=='diff':value=equal_except_volatile(decode(row['left']),decode(row['right']),schema(row['schema']))
            elif row['op']=='snapshot':
                reference=create_volatile(decode(row['data']));value=[reference.get(),[entry['path'] for entry in volatile_entries(reference)]]
            else:
                target=schema(row['schema']);parsed=target(decode(row['data']),row.get('options'))
                value=dict(parsed=parsed,simplified=target.simplify(parsed),paths=[entry['path'] for entry in volatile_entries(parsed)])
            results.append(dict(ok=True,value=normalize(value)))
        except Exception as error:
            results.append(dict(ok=False,name=getattr(error,'name',type(error).__name__),message=str(error),path=getattr(error,'options',{}).get('path',[])))
    return results


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_volatile.mts',prepare=prepare,scope='Immutable config references, supported schema placements/defaults, strict nested comparison and raw volatile metadata comparison. Python has no native JS URL object; URL renderer behavior is outside this corpus.',
               extra_inputs=[ROOT/'dsh/cordis/schema.py',ROOT/'dsh/cordis/utils.py',ROOT/'dsh/cordis/volatile.py',ROOT/'dsh/cordis/loader_diff.py',Path(__file__).resolve(),ROOT/'reference/vendor/schemastery/src/index.ts',ROOT/'reference/vendor/cosmokit/src/volatile.ts',ROOT/'reference/vendor/cosmokit/src/types.ts',ROOT/'reference/vendor/loader/src/config/diff.ts'])
