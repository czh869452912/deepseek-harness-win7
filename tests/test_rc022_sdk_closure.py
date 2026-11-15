import asyncio
import io
import json

import pytest

from scripts.rc022_sdk_closure_probe import observe, Input
from dsh.sdk.transport import JsonRpcLineTransport


@pytest.mark.asyncio
async def test_first_failure_final_frame_and_write_recovery_match_source():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==11 and all(row['pending']==0 for row in rows.values())
    assert rows['error']['first']['original'] and rows['error']['later']['original']
    assert rows['final-frame']['first']==dict(value=dict(ok=True))
    assert rows['final-frame']['later']['error']=='JSON-RPC input closed'
    assert rows['close-before-start']['later']['error']=='JSON-RPC transport closed'
    assert rows['write-failure']['later']==dict(value='recovered')
    assert rows['utf8-split']['seen']==[dict(method='unicode',params=dict(text='你好'))]
    assert rows['malformed-json']['seen']==[]


@pytest.mark.asyncio
async def test_real_pipe_final_frame_is_observed_before_eof():
    import os
    from dsh.sdk.stdio import StdioInput
    read_fd,write_fd=os.pipe();source=os.fdopen(read_fd,'rb',buffering=0)
    reader=StdioInput(source);output=io.StringIO();transport=JsonRpcLineTransport(reader,output)
    transport.start();pending=asyncio.create_task(transport.request('last',{}));await asyncio.sleep(0)
    identity=json.loads(output.getvalue())['id']
    try:
        os.write(write_fd,(json.dumps(dict(id=identity,result=dict(last='你好')),ensure_ascii=False)+'\n').encode('utf-8'))
        os.close(write_fd);write_fd=None
        assert await asyncio.wait_for(pending,3)==dict(last='你好')
        for _ in range(100):
            if reader.readableEnded:break
            await asyncio.sleep(.005)
        with pytest.raises(RuntimeError,match='input closed'):await transport.request('after',{})
        assert not transport.pending
    finally:
        transport.close();await reader.close();source.close()
        if write_fd is not None:os.close(write_fd)


@pytest.mark.asyncio
async def test_caller_cancel_retains_no_waiter_and_late_frame_is_ignored():
    incoming=Input();output=io.StringIO();transport=JsonRpcLineTransport(incoming,output);transport.start()
    pending=asyncio.create_task(transport.request('cancel',{}));await asyncio.sleep(0)
    identity=json.loads(output.getvalue())['id'];pending.cancel()
    with pytest.raises(asyncio.CancelledError):await pending
    assert not transport.pending
    incoming.emit('data',json.dumps(dict(id=identity,result='late'))+'\n')
    await asyncio.gather(*list(transport.tasks));transport.close()
    assert not any(incoming.listeners.values())
