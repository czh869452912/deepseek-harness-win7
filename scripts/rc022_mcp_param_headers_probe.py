"""Compare pure SDK declaration reachability and primitive header conversion."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[]
    names=['Trace','trace','',None,False,1,'two words','a\nb','[a]','a:b','a/b','a=b','中文','!#$%&\'*+-.^_`|~012AZaz','x\t','x\r','a\\b','a"b','😀']
    types=['string','integer','boolean','number','object','array','null',None,['string','null']]
    for name in names:
        for kind in types:
            rows.append(dict(schema=dict(type='object',properties=dict(value={'type':kind,'x-mcp-header':name})),args=dict(value='ok')))
    for keyword in ('items','prefixItems','contains','additionalProperties','unevaluatedProperties','unevaluatedItems','propertyNames','patternProperties','dependentSchemas','oneOf','anyOf','allOf','not','if','then','else','$defs','definitions'):
        leaf={'type':'string','x-mcp-header':'Owned'}
        for sub in (leaf,[leaf],dict(branch=leaf),dict(properties=dict(inner=leaf))):
            rows.append(dict(schema={keyword:sub},args={}))
    values=['','ascii',' two ','\t','a\tb','\x00','\x7f','中文','😀','\ud800','=?base64?YWJj?=','=?base64?incomplete',False,True,None,0,-0.0,1,1.25,1e-7,1e21,9007199254740991,9007199254740992,[],{}]
    for value in values:
        rows.append(dict(schema=dict(properties=dict(outer=dict(properties=dict(value={'type':'string','x-mcp-header':'Trace'})))),args=dict(outer=dict(value=value))))
    rows.extend([
        dict(schema={'x-mcp-header':'Root','type':'string'},args='bad'),
        dict(schema=dict(properties={'a':{'type':'string','x-mcp-header':'Trace'},'b':{'type':'number','x-mcp-header':'trace'}}),args=dict(a='first',b=2)),
        dict(schema=dict(properties={'10':{'type':'string','x-mcp-header':'ten'},'2':{'type':'boolean','x-mcp-header':'two'}}),args={'2':False,'10':'ten'}),
        dict(schema=dict(properties=dict(outer=dict(properties={'0':{'type':'string','x-mcp-header':'First'},'length':{'type':'integer','x-mcp-header':'Length'},'01':{'type':'string','x-mcp-header':'Missing'}}))),args=dict(outer=['hello','world'])),
        dict(schema=dict(properties=[{'type':'string','x-mcp-header':'ArraySchema'}]),args=['value']),
        dict(schema=dict(properties=dict(value={'type':'string','x-mcp-header':'Missing'})),args={}),
        dict(schema=dict(properties=dict(value={'$ref':'#/unknown','type':'string','x-mcp-header':'Sibling'})),args=dict(value='accepted')),
    ])
    return rows


async def observe():
    from dsh.mcp.param_headers_current import scan_declarations,build_param_headers
    rows=[]
    for case in cases():
        scan=scan_declarations(case['schema']);row=dict(scan=scan)
        if scan['valid']:row['headers']=build_param_headers(scan['declarations'],case['args'])
        rows.append(row)
    return rows


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_param_headers.mts','Actual pinned SDK pure header scanner/builder: declaration type/token/uniqueness, static reachability across all excluded schema keywords, JS key order, nested/array args, primitive conversion, whitespace/base64 sentinels, UTF-8 and surrogate replacement. Client filtering and wire recovery are separate consumers.',extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/mcp/param_headers_current.py'],prepare=prepare)
