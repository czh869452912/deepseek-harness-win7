"""Owned local stdio peer; no network or credentials are involved."""
import json
import sys
from pathlib import Path

log=Path(sys.argv[1]);counter=Path(sys.argv[2]);resources=sys.argv[3]=='resources'
generation=int(counter.read_text(encoding='utf-8')) if counter.exists() else 0
pending=[]


def send(identity,value=None,error=None):
    packet=dict(jsonrpc='2.0',id=identity)
    packet['error' if error is not None else 'result']=error if error is not None else value
    sys.stdout.write(json.dumps(packet,separators=(',',':'))+'\n');sys.stdout.flush()


for line in sys.stdin:
    packet=json.loads(line)
    with log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(generation=generation,packet=packet))+'\n')
    method=packet.get('method');identity=packet.get('id');params=packet.get('params',{})
    if identity is None:continue
    if method=='initialize':
        generation+=1;counter.write_text(str(generation),encoding='utf-8')
        send(identity,dict(protocolVersion=params['protocolVersion'],capabilities=dict(tools={},**({'resources':{}} if resources else {})),serverInfo=dict(name='resource-peer',version='1'),instructions='Use literal {{model}} for generation '+str(generation)+'  \n'))
    elif method=='tools/list':send(identity,dict(tools=[]))
    elif method in ('resources/list','resources/templates/list'):
        if params.get('cursor')=='bad':send(identity,dict(resources=42));continue
        if params.get('cursor')=='stop':break
        if params.get('cursor')=='hold':pending.append(identity);continue
        item=dict(uri='doc://a',name='one',description='generation '+str(generation),generation=generation) if method=='resources/list' else dict(uriTemplate='doc://{name}',name='one',generation=generation)
        send(identity,{'resources' if method=='resources/list' else 'resourceTemplates':[item],'nextCursor':'next'})
    elif method=='resources/read':send(identity,dict(contents=[dict(uri=params['uri'],blob='YWJj',generation=generation)]))
    else:send(identity,error=dict(code=-32601,message='Method not found'))
