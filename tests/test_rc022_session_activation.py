import asyncio
from types import SimpleNamespace as NS
import pytest

from scripts.rc022_session_activation_probe import observe
from scripts.rc022_subagent_fixture import setup
from dsh.api.session_agents_authorized import AuthorizedSessionAgents
from dsh.api.session_agents_current import ApiSessionPresetConflict
from dsh.typert.current import CurrentTypertRegistry


async def runtime(path):
    fixture = await setup(path/'journal')
    await fixture.ctx.plugin(CurrentTypertRegistry)
    fixture.ctx.set_service('agentDefaultModel', NS(currentSelection=lambda:dict(provider='script', model='model')))
    return fixture, AuthorizedSessionAgents(fixture.ctx)


@pytest.mark.asyncio
async def test_actual_activation_commands_and_recorded_model(tmp_path):
    rows = {row['name']:row for row in await observe(tmp_path)}
    assert len(rows) == 19
    assert rows['dynamic-default']['model']['model'] == 'changed'
    assert rows['ordered-claims']['presets'] == ['coding', 'reviewing']
    assert rows['ordered-claims']['same'] and rows['omitted-default']['preset'] == 'coding'
    assert rows['selected-before-save']['duplicateSkipped'] and rows['selected-before-save']['savePending']
    assert rows['actual-request']['requests'] == [dict(provider='record', model='selected')]
    for name in ('started-mints', 'archived-mints', 'placement-mints', 'cold-started-mints'):
        assert rows[name]['minted']
    assert rows['cold-blank-reuse']['named'] and rows['cold-blank-reuse']['preset'] == 'coding'
    assert rows['settled']['claims'] == rows['settled']['saves'] == 0


@pytest.mark.asyncio
async def test_cancelled_create_waiter_keeps_claim_and_next_request_ordered(tmp_path):
    fixture, agents = await runtime(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    original = agents.composeAgent
    calls = []
    async def compose(preset):
        calls.append(preset)
        if len(calls) == 1:
            entered.set(); await release.wait()
        return await original(preset)
    agents.composeAgent = compose
    request = dict(sessionId='ordered', cwd=str(tmp_path/'work'), reusable=lambda _:True)
    first = asyncio.ensure_future(agents.createSession(request))
    second = None
    try:
        await entered.wait()
        second = asyncio.ensure_future(agents.createSession(request))
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        await asyncio.sleep(0)
        assert calls == [None] and not second.done()
        release.set()
        result = await second
        assert result['agent'] is fixture.ctx.agents.get('ordered')
        assert calls == [None, None] and agents.claims == {}
    finally:
        release.set()
        await asyncio.gather(*list(agents.claims.values()), return_exceptions=True)
        if second is not None: await asyncio.gather(second, return_exceptions=True)
        await fixture.ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_rejected_claim_does_not_poison_later_create(tmp_path):
    fixture, agents = await runtime(tmp_path)
    original = agents.composeAgent
    calls = []
    async def compose(preset):
        calls.append(preset)
        if len(calls) == 1: raise RuntimeError('rejected preset preparation')
        return await original(preset)
    agents.composeAgent = compose
    request = dict(sessionId='retry', cwd=str(tmp_path/'work'), reusable=lambda _:True)
    try:
        results = await asyncio.gather(agents.createSession(request), agents.createSession(request), return_exceptions=True)
        assert isinstance(results[0], RuntimeError)
        assert results[1]['agent'] is fixture.ctx.agents.get('retry')
        assert agents.claims == {}
    finally: await fixture.ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_without_roster_named_preset_refuses_blank_reuse_only(tmp_path):
    fixture, agents = await runtime(tmp_path)
    request = dict(sessionId='blank', cwd=str(tmp_path/'work'), reusable=lambda _:True)
    try:
        initial = await agents.createSession(dict(request, agentPreset='unmounted'))
        assert initial['agentPreset'] is None
        with pytest.raises(ApiSessionPresetConflict):
            await agents.createSession(dict(request, agentPreset='unmounted'))
        initial['agent'].session.append('turn/start', dict(turn=1))
        other = await agents.createSession(dict(request, agentPreset='unmounted'))
        assert other['agent'].id != 'blank' and other['agentPreset'] is None
    finally: await fixture.ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_concurrent_cold_resolution_shares_published_agent(tmp_path):
    fixture, agents = await runtime(tmp_path)
    try:
        old = await fixture.ctx.agents.create(dict(sessionId='cold', meta=dict(cwd=str(tmp_path)), agentOptions=agents.agent_options()))
        old.agent.model.select(dict(provider='script', model='model'))
        await old.dispose()
        found = await asyncio.gather(*(agents.resolveAgent('cold') for _ in range(5)))
        assert all('agent' in row for row in found), [str(row.get('error')) for row in found]
        assert all(row['agent'] is found[0]['agent'] for row in found)
        assert fixture.ctx.agents.get('cold') is found[0]['agent']
        assert agents.resumes == {}
    finally: await fixture.ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_resume_writer_error_keeps_domain_code(tmp_path):
    from dsh.session.persistence import SessionAlreadyOwnedError
    fixture, agents = await runtime(tmp_path)
    async def blocked(*_): raise SessionAlreadyOwnedError('held')
    agents._resume = blocked
    try:
        result = await agents.resolveAgent('held')
        assert result['error'].code == 'session/writer-held'
        assert result['error'].details == dict(sessionId='held')
    finally: await fixture.ctx.fiber.dispose()
