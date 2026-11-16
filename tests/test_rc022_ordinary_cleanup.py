import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.subprocess import ordinary_authorized as ordinary


@pytest.mark.asyncio
@pytest.mark.parametrize('failed',[False,True])
async def test_public_completion_joins_handles_after_range_exit(monkeypatch,failed):
    entered=asyncio.Event();release=asyncio.Event();closed=[];done=asyncio.get_running_loop().create_future()
    async def exited():entered.set();await release.wait();return True
    raw=NS(pid=1,stdin=None,stdout=None,stderr=None,collected=NS(stdout=None,stderr=None),done=done,
        wait_for_exit=exited,_tree_alive=lambda:False,_proc=NS(close_handles=lambda:closed.append(True)),terminate=lambda:None)
    monkeypatch.setattr(ordinary,'LocalSubprocessHandle',lambda *_:raw)
    runtime=NS(live=set(),ordinary_cleanups=set())
    handle=ordinary.spawn(runtime,dict(argv=['controlled'],cwd='.',graceMs=100,stdio=dict(stdin='ignore',stdout='ignore',stderr='ignore')))
    error=RuntimeError('process failure')
    if failed:done.set_exception(error)
    else:done.set_result(NS(to_dict=lambda:dict(exitCode=0,signal=None)))
    await entered.wait();await asyncio.sleep(0)
    assert not handle.done.task.done() and handle in runtime.live and not closed
    release.set()
    if failed:
        with pytest.raises(RuntimeError) as captured:await handle.done
        assert captured.value is error
    else:assert await handle.done==dict(exitCode=0,signal=None)
    assert not runtime.live and closed==[True]


@pytest.mark.asyncio
async def test_direct_process_result_remains_available_with_live_descendants(monkeypatch):
    release=asyncio.Event();done=asyncio.get_running_loop().create_future();closed=[]
    async def exited():await release.wait();return True
    raw=NS(pid=1,stdin=None,stdout=None,stderr=None,collected=NS(stdout=None,stderr=None),done=done,
        wait_for_exit=exited,_tree_alive=lambda:True,_proc=NS(close_handles=lambda:closed.append(True)),terminate=lambda:None)
    monkeypatch.setattr(ordinary,'LocalSubprocessHandle',lambda *_:raw)
    runtime=NS(live=set(),ordinary_cleanups=set())
    handle=ordinary.spawn(runtime,dict(argv=['controlled'],cwd='.',graceMs=100,stdio=dict(stdin='ignore',stdout='ignore',stderr='ignore')))
    done.set_result(NS(to_dict=lambda:dict(exitCode=0,signal=None)))
    assert await asyncio.wait_for(handle.done.task,1)==dict(exitCode=0,signal=None)
    assert handle in runtime.live and not closed
    release.set();await handle.release
    assert not runtime.live and closed==[True]
