import asyncio
import threading

import pytest

from dsh.code_runtime.protocol import JsonLines, QueuedBytes, PendingCalls, IncomingBytes, ProtocolError


@pytest.mark.asyncio
async def test_paired_framing_and_actual_pending_call_limits(tmp_path):
    from scripts import rc022_ptc_protocol_probe as probe
    probe.WORKSPACE = tmp_path
    rows = await asyncio.wait_for(probe.observe(), 20)
    indexed = {row['name']: row for row in rows if row['name'] not in ('outgoing', 'pending')}
    assert indexed['fragmented']['values'] == ['你好🙂\ninside']
    assert indexed['consecutive']['values'] == ['a', 'b']
    assert indexed['exact']['failure'] is None
    assert indexed['replacement']['values'] == ['�']
    assert indexed['empty-eof']['failure'] == 'closed'
    for name in ('overflow', 'bad-json', 'non-object', 'array', 'space-prefix', 'empty-line',
                 'incomplete', 'length-prefix', 'bad-first-then-valid', 'non-json-number'):
        assert indexed[name]['failure'] == 'protocol'
    assert not indexed['bad-first-then-valid']['values']
    for row in rows:
        if row['name'] == 'pending':
            assert row['error'] == 'protocol' and row['calls'] == 1 and row['callerOwned']


def test_outgoing_and_pending_budgets_release_exact_charges():
    queue = QueuedBytes(20)
    line = queue.admit(dict(v='汉'))
    assert queue.size == len(line)
    with pytest.raises(ProtocolError, match='queued bytes'):
        queue.admit(dict(v='汉'))
    queue.release(line)
    assert queue.admit(dict(v='汉')) == line
    pending = PendingCalls(2, 8)
    charge = pending.admit('汉')
    assert charge == 5
    with pytest.raises(ProtocolError, match='pending binding calls'):
        pending.admit('汉')
    pending.release(charge)
    pending.admit(1)
    pending.admit(2)
    with pytest.raises(ProtocolError):
        pending.admit(3)


def test_reader_handoff_budget_is_released_on_stop():
    incoming, stopped = IncomingBytes(10), threading.Event()
    assert incoming.admit(10, stopped)
    entered, finished = threading.Event(), threading.Event()
    result = []
    def reader():
        entered.set()
        result.append(incoming.admit(1, stopped))
        finished.set()
    thread = threading.Thread(target=reader)
    thread.start()
    try:
        assert entered.wait(1) and not finished.is_set()
        stopped.set()
        assert finished.wait(1)
        assert result == [False]
    finally:
        stopped.set()
        thread.join(1)
    incoming.release(10)
    assert incoming.size == 0


@pytest.mark.parametrize('key', ['maxMessageBytes', 'maxPendingCalls', 'maxOldGenerationSizeMb'])
@pytest.mark.parametrize('value', [True, 0, -1, 1.5, float('inf'), 9007199254740992])
def test_current_runtime_rejects_invalid_integer_traffic_limits(key, value):
    from dsh.cordis import Context
    from dsh.code_runtime.ptc import PythonPtcRuntime
    with pytest.raises(ValueError):
        PythonPtcRuntime(Context(), {key:value})


@pytest.mark.asyncio
async def test_oversized_boot_and_binding_reply_fail_protocol_and_reap_process(tmp_path):
    from dsh.cordis import Context
    from dsh.code_runtime.ptc import PythonPtcRuntime
    ctx = Context()
    await ctx.plugin(PythonPtcRuntime, dict(maxMessageBytes=512, timeoutMs=3000))
    runtime = ctx.get('ptcRuntime')
    try:
        for program, bindings in [('return "'+'x'*600+'"', []),
                ('return await tools.large({})', [dict({'global':'tools'}, functions=dict(large=lambda args:'x'*1000))])]:
            result = await asyncio.wait_for(runtime.run(runtime.resolve(
                dict(program=program, bindings=bindings, cwd=str(tmp_path)))), 5)
            assert result['error']['kind'] == 'protocol'
            assert 'queued bytes' in result['error']['message']
            assert not runtime.runs
    finally:
        await ctx.fiber.dispose()


@pytest.mark.parametrize('key', ['timeoutMs', 'maxTimeoutMs'])
def test_current_runtime_rejects_timer_overflow(key):
    from dsh.cordis import Context
    from dsh.code_runtime.ptc import PythonPtcRuntime
    with pytest.raises(ValueError, match='timer bound'):
        PythonPtcRuntime(Context(), {key:2147483648})
