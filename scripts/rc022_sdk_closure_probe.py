"""Paired terminal failure ownership and final-frame ordering of SDK transport."""
import asyncio
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.core.abort import AbortController
from dsh.core.session.json import UNDEFINED
from dsh.sdk.transport import JsonRpcLineTransport


class Input:
    def __init__(self):self.listeners={}
    def on(self,name,callback):self.listeners.setdefault(name,[]).append(callback)
    def off(self,name,callback):self.listeners[name]=[fn for fn in self.listeners.get(name,[]) if fn!=callback]
    def emit(self,name,*args):
        for callback in list(self.listeners.get(name,[])):callback(*args)


async def observe():
    rows=[]
    for kind in ['close-before-start','eof','error','final-frame','pre-abort','write-failure','error-shape','error-array','missing-result','malformed-json','utf8-split']:
        incoming=Input();output=io.StringIO();transport=JsonRpcLineTransport(incoming,output);original=RuntimeError('first failure');controller=AbortController();seen=[]
        transport.on_notification(lambda method,params:seen.append(dict(method=method,params=params)))
        if kind=='close-before-start':transport.close()
        transport.start()
        async def take(signal=None):
            try:
                value=await transport.request('probe',{},signal)
                return dict(value=None if value is UNDEFINED else value)
            except Exception as error:
                return dict(error=str(error),original=error is original,code=None if getattr(error,'code',UNDEFINED) is UNDEFINED else error.code,data=None if getattr(error,'data',UNDEFINED) is UNDEFINED else error.data)
        try:
            if kind=='pre-abort':controller.abort('cancelled')
            if kind=='write-failure':
                class Broken:
                    def write(self,_):raise RuntimeError('write failed')
                transport.output=Broken()
            pending=asyncio.create_task(take(controller.signal));await asyncio.sleep(0)
            if kind in ('eof','error'):
                incoming.emit('end') if kind=='eof' else incoming.emit('error',original)
                incoming.emit('error',RuntimeError('second failure'));incoming.emit('end');transport.close();controller.abort('later')
            elif kind not in ('close-before-start','pre-abort','write-failure'):
                identity=json.loads(output.getvalue().splitlines()[0])['id']
                frame=dict(id=identity,result=dict(ok=True))
                if kind=='error-shape':frame=dict(id=identity,error=dict(code='bad',message=4,data=dict(why=1)))
                if kind=='error-array':frame=dict(id=identity,error=[])
                if kind=='missing-result':frame=dict(id=identity)
                if kind=='malformed-json':incoming.emit('data','not json\nnull\n[]\n{"method":"bad","params":{"n":NaN}}\n')
                if kind=='utf8-split':
                    wire=json.dumps(dict(method='unicode',params=dict(text='你好')),ensure_ascii=False).encode('utf-8')+b'\n'
                    for byte in wire:incoming.emit('data',bytes([byte]))
                incoming.emit('data',json.dumps(frame)+'\n')
                if kind=='final-frame':incoming.emit('end')
            first=await pending
            if kind=='write-failure':
                transport.output=output
                next_task=asyncio.create_task(take());await asyncio.sleep(0)
                identity=json.loads(output.getvalue().splitlines()[0])['id'];incoming.emit('data',json.dumps(dict(id=identity,result='recovered'))+'\n')
                later=await next_task
            elif kind in ('close-before-start','eof','error','final-frame'):
                later=await take(controller.signal)
            else:later=None
            rows.append(dict(name=kind,first=first,later=later,seen=seen,pending=len(transport.pending)))
        finally:
            transport.close();await asyncio.gather(*list(transport.tasks),return_exceptions=True)
            assert not any(incoming.listeners.values())
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_closure.mts','Actual Source/native SDK transports: first permanent failure, close-before-start, EOF, final response immediately before EOF, failure-before-abort, pre-abort, recoverable write failure, normalized response errors, ignored invalid JSON and byte-split UTF8. Python streams remain caller-owned; asynchronous Writable callback flush is a platform-specific boundary.',[Path(__file__).resolve(),ROOT/'dsh/sdk/transport.py'])
