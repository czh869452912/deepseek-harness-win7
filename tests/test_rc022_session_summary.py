import asyncio
from types import SimpleNamespace as NS

import pytest

import dsh.api.session_list_authorized as module
from dsh.api.session_list_authorized import AuthorizedSessionList
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.core.session.current_session import CurrentSessionStore
from dsh.cordis import Context
from dsh.session.query_current import CurrentSessionQueryService
from scripts.rc022_session_summary_probe import observe


@pytest.mark.asyncio
async def test_actual_live_and_cold_projection_summaries(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 10
    assert rows['blank-live']['value']['agentAvailable']
    assert rows['prompt-still-blank']['value']['blank'] and rows['prompt-still-blank']['recency']
    assert not rows['started-live']['value']['blank']
    assert 'imageLimits' in rows['all-wire']['value']['values']
    assert 'imageLimits' not in rows['blank-live']['value']['projections']['values']
    cold = rows['cold-cached-list']
    assert cold['opens'] == cold['agents'] == 0 and cold['value'][0]['formatStatus'] == 'current'
    assert cold['value'][0]['projections']['kind'] == 'cached'
    seeded = rows['seeded-header']['value']
    assert seeded['blank'] and seeded['projections']['asOfSeq'] == 7
    assert 'imageLimits' not in seeded['projections']['values']
    assert not rows['cold-miss']['value']['blank'] and rows['cold-miss']['value']['formatStatus'] == 'migration-required'
    assert not rows['attached-no-agent']['value']['agentAvailable']
    assert rows['wire-failure-keeps-metadata']['value']['blank'] and 'projections' not in rows['wire-failure-keeps-metadata']['value']


def schedule_fixture(monkeypatch, phases, cost=8, budget=8, cwd=True):
    clock = [0.0]; trace = []; scheduled = []
    monkeypatch.setattr(module, 'time', NS(perf_counter=lambda: clock[0]))
    headers = [SessionHeader(str(i), created_at=1, cwd='C:/test' if cwd else None, version=4) for i in range(len(phases))]
    attached = {header.id: NS(header=header, id=header.id) for header, phase in zip(headers, phases) if phase == 'live'}
    records = [dict(header=header, formatStatus='current') for header in headers]
    async def list_sessions(signal): return records
    services = dict(sessionQuery=NS(listSessions=list_sessions), sessions=NS(get=lambda sid: attached.get(sid)))
    listing = AuthorizedSessionList(NS(get=services.get), budget)
    def summary(header, session=None, format_status=None):
        clock[0] += cost / 1000.0
        trace.append(header.id)
        if scheduled: scheduled.pop(0)(header)
        return dict(sessionId=header.id, updatedAt=1)
    listing._summary = summary
    return listing, clock, trace, scheduled, services, attached


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['live', 'cold'])
async def test_cooperative_budget_allows_other_work_between_expensive_rows(monkeypatch, phase):
    listing, clock, trace, scheduled, _, _ = schedule_fixture(monkeypatch, [phase] * 3)
    def observe(header): asyncio.get_running_loop().call_soon(trace.append, 'other:' + header.id)
    scheduled.extend([observe] * 3)
    values = await listing.list()
    assert trace == ['0', 'other:0', '1', 'other:1', '2', 'other:2']
    assert [value['sessionId'] for value in values] == ['0', '1', '2']


@pytest.mark.asyncio
async def test_budget_accumulates_across_phases_and_resets_after_yield(monkeypatch):
    listing, clock, trace, scheduled, _, _ = schedule_fixture(monkeypatch, ['live', 'cold', 'cold'], cost=4)
    def first(_):
        def other(): clock[0] += 1; trace.append('other')
        asyncio.get_running_loop().call_soon(other)
    scheduled.append(first)
    await listing.list()
    assert trace == ['0', '1', 'other', '2']


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['live', 'cold'])
@pytest.mark.parametrize('abort_at', ['0', '2'])
async def test_cancellation_after_expensive_first_or_last_row(monkeypatch, phase, abort_at):
    listing, _, trace, scheduled, _, _ = schedule_fixture(monkeypatch, [phase] * 3)
    abort = AbortController(); primary = RuntimeError('stop rows')
    def observe(header):
        if header.id == abort_at: asyncio.get_running_loop().call_soon(abort.abort, primary)
    scheduled.extend([observe] * 3)
    with pytest.raises(RuntimeError) as caught: await listing.list(abort.signal)
    assert caught.value is primary and trace == (['0'] if abort_at == '0' else ['0', '1', '2'])


@pytest.mark.asyncio
async def test_skipped_classification_counts_toward_budget(monkeypatch):
    listing, clock, trace, _, services, _ = schedule_fixture(monkeypatch, ['cold'] * 3, cost=0, cwd=False)
    abort = AbortController(); lookups = []
    def lookup(sid):
        lookups.append(sid); clock[0] += .004
        if sid == '0': asyncio.get_running_loop().call_soon(abort.abort, RuntimeError('stop classification'))
    services['sessions'].get = lookup
    with pytest.raises(RuntimeError, match='stop classification'): await listing.list(abort.signal)
    assert lookups == ['0', '1'] and not trace


@pytest.mark.asyncio
async def test_cheap_last_row_still_checks_synchronous_abort(monkeypatch):
    listing, _, trace, scheduled, _, _ = schedule_fixture(monkeypatch, ['cold'] * 2, cost=0)
    abort = AbortController()
    scheduled.extend([lambda _: None, lambda _: abort.abort(RuntimeError('last row'))])
    with pytest.raises(RuntimeError, match='last row'): await listing.list(abort.signal)
    assert trace == ['0', '1']


@pytest.mark.asyncio
async def test_query_preserves_cold_format_status_and_live_current_precedence():
    ctx = Context()
    CurrentSessionStore(ctx, 4)
    headers = [dict(version=4, id='current', createdAt=2, cwd='C:/test', isSeeded=False), dict(version=3, id='old', createdAt=1, cwd='C:/test', isSeeded=False)]
    async def persisted(_): return [dict(header=headers[0], formatStatus='current'), dict(header=headers[1], formatStatus='migration-required')]
    ctx.set_service('sessionPersistence', NS(list=persisted))
    query = CurrentSessionQueryService(ctx)
    try:
        values = await query.listSessions()
        assert [value['formatStatus'] for value in values] == ['current', 'migration-required']
        attached = ctx.sessions.create('current', meta=dict(createdAt=2, cwd='C:/test'))
        value = (await query.listSessions())[0]
        assert value['formatStatus'] == 'current' and value['live'] and value['persisted']
        value['header'].cwd = 'mutated'
        assert attached.header.cwd == 'C:/test' and headers[0]['cwd'] == 'C:/test'
    finally: await ctx.fiber.dispose()
