"""Pair exact stream frames and the actual upstream bounded inbox class."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    messages=['{','[]','null','NaN','{"type":"item","streamId":"s","value":1e400}',
              '{"type":"item","streamId":"s","value":-0}',
              '{"type":"item","streamId":"s","value":[-0]}',
              '{"type":"item","streamId":"s","value":9007199254740993}']
    for value in [dict(type='open',streamId='s',endpoint='fixture/echo',payload={}),dict(type='item',streamId='s'),dict(type='item',streamId='s',value=dict(text='中文')),dict(type='end',streamId='s'),dict(type='cancel',streamId='s'),dict(type='error',streamId='s',error=dict(code='',message='',details={}))]:
        for change in ({},{'streamId':''},{'streamId':2},{'extra':None}):messages.append(json.dumps(dict(value,**change),ensure_ascii=False))
    messages.extend(json.dumps(value) for value in [dict(type='open',streamId='s',endpoint='fixture'),dict(type='item',streamId='s',value=None),dict(type='error',streamId='s',error=dict(code='x',message='no',details=[])),dict(type='error',streamId='s',error=dict(code='x',message='no',details={},extra=True))])
    boxes=[
        ('drain',[['push','a',4],['push','b',4],['end'],['read'],['read'],['read']]),
        ('refill',[['push','a',8],['read'],['push','b',8],['read'],['end'],['read']]),
        ('overflow',[['push','a',4],['push','b',5],['push','ignored',1],['read']]),
        ('after-end',[['push','a',1],['end'],['end'],['push','bad',1],['read']]),
        ('after-drained-end',[['end'],['read'],['push','bad',1],['read']]),
        ('closed',[['push','a',8],['return'],['push','ignored',9],['end'],['read']]),
        ('sticky-failure',[['push','a',8],['fail','first'],['fail','second'],['read']]),
        ('closed-failure',[['fail','first'],['return'],['read']]),
        ('consumer',[['claim'],['claim'],['return']]),
        ('pending-item',[['start'],['push','wake',8],['pending'],['return']]),
        ('pending-end',[['start'],['end'],['pending']]),
        ('pending-failure',[['start'],['fail','wake'],['pending']]),
        ('pending-return',[['start'],['return'],['pending']]),
        ('concurrent-read',[['start'],['read'],['end'],['pending']]),
    ]
    return dict(messages=messages,boxes=boxes)


async def observe():
    from dsh.typert.stream_protocol import parse_client_message,parse_server_message
    from dsh.typert.uplink_inbox import UplinkInbox
    from dsh.typert.remote import remote_error_of
    from dsh.typert.rpc_result import json_projection
    rows=[]
    for direction,parse in [('client',parse_client_message),('server',parse_server_message)]:
        for index,text in enumerate(cases()['messages']):
            try:
                import math
                value=parse(text)
                def negative_zero(value):
                    if type(value) is float:return value==0 and math.copysign(1,value)<0
                    if isinstance(value,(dict,list)):return any(negative_zero(item) for item in (value.values() if isinstance(value,dict) else value))
                    return False
                result=dict(value=value,negativeZero=negative_zero(value))
            except Exception as error:result=dict(error=str(error))
            rows.append(dict(direction=direction,index=index,**result))
    async def read(box):
        try:return dict(done=False,value=await box.__anext__())
        except StopAsyncIteration:return dict(done=True)
        except Exception as error:return dict(error=remote_error_of(error) or dict(message=str(error)))
    for name,actions in cases()['boxes']:
        violations=[];box=UplinkInbox(8,'fixture/echo',lambda error:violations.append(remote_error_of(error)));results=[];pending=None
        for action in actions:
            kind=action[0]
            if kind=='push':box.push(action[1],action[2])
            elif kind=='end':box.end()
            elif kind=='fail':box.fail(RuntimeError(action[1]))
            elif kind=='return':await box.aclose();results.append(dict(done=True))
            elif kind=='read':results.append(await read(box))
            elif kind=='start':pending=asyncio.create_task(read(box));await asyncio.sleep(0)
            elif kind=='pending':results.append(await pending)
            elif kind=='claim':
                try:box.__aiter__();results.append(dict(claimed=True))
                except Exception as error:results.append(dict(error=dict(message=str(error))))
        rows.append(dict(name=name,results=results,violations=violations,bytes=box.bytes))
        await box.aclose()
    return json_projection(rows)


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases(),ensure_ascii=False),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_uplink_inbox.mts','Exact client/server frame parsers and bounded single-consumer UplinkInbox: draining/refill, overflow, half-close violations, failure/return priority, pending reads and early close. Source inbox class is captured from an actual RemoteStreamMuxServer upgrade; queue observations exercise that class directly, not a source rewrite.',[Path(__file__).resolve(),ROOT/'dsh/typert/stream_protocol.py',ROOT/'dsh/typert/uplink_inbox.py'],prepare=prepare)
