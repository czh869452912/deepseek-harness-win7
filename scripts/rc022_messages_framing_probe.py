"""Messages SSE bytes and provider error facts against pinned actual helpers."""
import base64
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
NOW=1750000000000


def cases():
    texts=['data: {"type":"ping"}\n\n',': heartbeat\n\ndata: {"type":"ping"}\n\n',
        'event: ping\ndata: {"type":"ping"}\n\n','event:\ndata: {"type":"ping"}\n\n',
        'data: {"type":\ndata: "ping"}\n\n','id: a\nretry: bad\nunknown: ignored\ndata: {"type":"ping"}\n\n',
        'event: ping\n\n','data\n\n','data: bad\n\n','data: []\n\n','data: null\n\n','data: {}\n\n',
        'event: wrong\ndata: {"type":"ping"}\n\n','data: {"type":"error","error":{"type":"authentication_error","message":"denied"}}\n\n',
        '\ufeffdata: {"type":"ping","text":"中文😀"}\n\n','ï»¿data: {"type":"ping"}\n\n',
        'data: {"type":"ping"}\n','data: {"type":"ping"}',': heartbeat','data: {"type":"ping"}\r',
        'data: {"type":"ping"}\r\r', 'data: {"type":"ping"}\r\rX',
        'data: {"type":"ping"}\n\ndata: bad\n\n']
    frames=[]
    for text in texts:
        variants=[text,text.replace('\n','\r\n'),text.replace('\n','\r')]
        for value in variants:
            payload=value.encode('utf-8')
            for size in [1,2,7,len(payload) or 1]: frames.append([base64.b64encode(payload[index:index+size]).decode('ascii') for index in range(0,len(payload),size)])
    frames.extend([[base64.b64encode(value).decode('ascii')] for value in [b'data: {"type":"ping","text":"\xff"}\n\n',b'\xef\xbb',b'data: {"type":"ping"}\n\n\xff']])
    errors=[]
    messages=['ordinary','insufficient_quota','context_length_exceeded','out of credits','maximum context length','input too long for this model',
        'quota_exceeded','中文quota_exceeded','quota\u0085exceeded','quota\u00a0exceeded','quota\ufeffexceeded',
        'quota\u001cexceeded','context\u0085length_exceeded','context\ufefflength_exceeded','']
    for status in [None,400,401,402,403,404,413,429,500,503]:
        for kind in ['','authentication_error','permission_error','rate_limit_error','invalid_request_error','api_error','overloaded_error']:
            for message in messages: errors.append(dict(raw=dict(error=dict(type=kind,code='provider_code',message=message)),status=status,headers={}))
    for retry in ['0','1','000.25','1.5','1.','.5','+1','-1','1e2','0x10','Infinity','NaN','9'*400,
        'Wed, 21 Oct 2099 07:28:00 GMT','2099-01-01T00:00:00Z','2099-01-01T00:00:00','+275760-09-13T00:00:00.000Z','+275760-09-14T00:00:00.000Z','garbage']:
        errors.append(dict(raw=None,status=429,headers={'retry-after':retry,'request-id':' primary ','x-request-id':'secondary'}))
    for headers in [{'request-id':'','x-request-id':'secondary'},{'x-request-id':'secondary'},{'x-deepseek-request-id':'third'},{}]:
        errors.append(dict(raw={'error':{'message':'bad'}},status=500,headers=headers))
    return dict(frames=frames,errors=errors)


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    import dsh.llm.deepseek_messages_errors as errors
    from dsh.llm.deepseek_messages_sse import parseSse
    rows=[];inputs=cases()
    for index,chunks in enumerate(inputs['frames']):
        pulses=[];values=[];closed=[]
        async def body():
            try:
                for chunk in chunks: yield base64.b64decode(chunk)
            finally: closed.append(True)
        result={}
        try:
            async for event in parseSse(body(),lambda:pulses.append(True)): values.append(event)
        except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        # Source's stream pipeline may prefetch comments after a fatal frame;
        # compare pulse counts for complete valid streams only.
        rows.append(dict(kind='sse',index=index,values=values,**(dict(pulses=len(pulses)) if not result else {}),**result))
    previous=errors.time.time
    try:
        errors.time.time=lambda:NOW/1000
        for index,case in enumerate(inputs['errors']):
            try:
                error=errors.providerError(case['raw'],case['status'],case['headers'])
                result=dict(failure=error.failure,detail=errors.providerErrorDetail(case['raw']))
            except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
            rows.append(dict(kind='error',index=index,**result))
    finally: errors.time.time=previous
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_messages_framing.mts','Original/native actual SSE framing and JSON events across arbitrary UTF-8/CRLF chunk boundaries, '
        'comments, named events, malformed JSON/type and ignored unterminated tails. Complete-stream activity counts; fatal frames exclude pipeline-prefetch timing. '
        'Provider error precedence, shared JS regex boundaries, retry-after date/numeric parsing and request-id precedence at frozen wall time.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/deepseek_messages_sse.py',ROOT/'dsh/llm/deepseek_messages_errors.py',ROOT/'dsh/llm/provider_errors.py'],prepare=prepare)
