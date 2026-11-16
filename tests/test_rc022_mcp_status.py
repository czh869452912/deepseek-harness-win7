import asyncio
import gc
import weakref

import pytest

from dsh.mcp.status_current import McpStatusCell,register_status_cell
from dsh.mcp.deadline_current import with_deadline
from scripts.rc022_mcp_status_probe import observe


def test_paired_status_diagnostics_and_deadline_observations():
    value=asyncio.run(observe())
    assert value['before']==[['first','connected'],['other','connected'],'sync','async-start']
    assert value['lifetime']==dict(unknown=True,same=True,lookup=True,readable=True)
    assert value['deadline']=='Error: deadline exceeded' and value['lateValue']==7
    assert len(value['warns'])==4 and value['warns'][1][0]=='new'


def test_status_cell_has_fiber_lifetime_without_global_warning_sink_retention():
    class Owner:pass
    owner=Owner();cell=register_status_cell(owner,lambda *args,retained=owner:None)
    owner_ref,cell_ref=weakref.ref(owner),weakref.ref(cell)
    del owner,cell
    gc.collect()
    assert owner_ref() is None and cell_ref() is None


def test_status_listener_identity_and_snapshot_iteration():
    cell=McpStatusCell(lambda *_:None);events=[]
    def listener(value):events.append(value)
    one=cell.onChange(listener);two=cell.onChange(listener)
    cell.update(dict(state='connecting',attempt=1))
    assert len(events)==1
    one();cell.update(dict(state='connecting',attempt=2));two()
    assert len(events)==1


def test_cancelling_deadline_caller_does_not_cancel_operation():
    async def run():
        operation=asyncio.get_running_loop().create_future()
        caller=asyncio.create_task(with_deadline(operation,10000,'unused'))
        await asyncio.sleep(0);caller.cancel()
        with pytest.raises(asyncio.CancelledError):await caller
        assert not operation.cancelled()
        operation.set_result('finished');assert await operation=='finished'
    asyncio.run(run())


def test_sdk_negotiation_failure_keeps_cause_for_current_diagnostics():
    from dsh.mcp.negotiation_current import classify_probe_outcome
    from dsh.mcp.diagnostic_current import describe_error
    cause=TypeError('fetch failed')
    error=classify_probe_outcome(dict(kind='network-error',error=cause),dict(environment='node'))['error']
    assert error.cause is cause
    assert describe_error(error)=='SdkError: Version negotiation probe failed: fetch failed, cause: TypeError: fetch failed'
