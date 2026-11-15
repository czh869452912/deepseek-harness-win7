import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.shell.jobs_current import process_job,process_outcome
from scripts.rc022_shell_job_probe import observe


@pytest.mark.asyncio
async def test_shell_bridge_and_marker_contracts():
    rows=await observe()
    assert len(rows)==25
    assert rows[1]['value']==dict(status='completed',detail='exit code: 5')
    assert rows[-4]['originalError'] is True
    assert rows[-3]['result']['status']=='killed' and rows[-3]['originalError'] is False
    assert rows[-1]['result']['detail']=='0' and rows[-1]['originalError'] is True
    assert all(row['trace']==['start','prepared','kill'] for row in rows if row['name'] in ('preparation','running'))


@pytest.mark.asyncio
async def test_cancelled_waiter_cannot_cancel_owned_preparation_or_process():
    gate=asyncio.get_running_loop().create_future();done=asyncio.get_running_loop().create_future();kills=[]
    process=NS(done=done,kill=lambda:kills.append('kill'),status='completed',exitCode=0,signal=None,sandbox=None)
    async def start(signal):return await gate
    hooks=process_job(start,process_outcome)
    async def wait():return await hooks.done
    waiter=asyncio.create_task(wait());await asyncio.sleep(0);waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    assert not gate.cancelled() and not kills
    gate.set_result(process);done.set_result(None)
    assert await hooks.done==dict(status='completed',detail='exit code: 0')
    assert hooks.failure() is None


@pytest.mark.asyncio
async def test_late_process_kill_error_still_awaits_settlement_and_keeps_original_failure():
    gate=asyncio.get_running_loop().create_future();done=asyncio.get_running_loop().create_future();original=RuntimeError('kill failed')
    def kill():raise original
    process=NS(done=done,kill=kill,status='running',exitCode=None,signal=None,sandbox=None)
    async def start(signal):return await gate
    hooks=process_job(start,process_outcome);hooks.cancel('before publication');gate.set_result(process)
    for _ in range(4):await asyncio.sleep(0)
    assert not hooks.done.task.done() and hooks.failure() is None
    done.set_result(None)
    assert await hooks.done==dict(status='failed',detail='kill failed')
    assert hooks.failure()['error'] is original
