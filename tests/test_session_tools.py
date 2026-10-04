import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin, ToolArgsError
from dsh.core.tools import ToolExecutionInput
from dsh.guard.timeout_policy import ToolCallTimeoutPolicyPlugin
from dsh.session.query_engine import SqliteSessionQueryPlugin
from dsh.session.session_query import SessionQueryError
from dsh.session.tool_query import ToolSessionQueryPlugin, resolve_config
from dsh.session import tool_query_boundary as boundary
from dsh.session import tool_query_workspace as workspace


@pytest.mark.asyncio
async def test_optional_plugin_registers_and_reverses_all_five_tools_and_prompt():
    context = Context()
    await context.plugin(SessionPlugin)
    await context.plugin(SystemPrompt)
    await context.plugin(ToolsPlugin)
    await context.plugin(SqliteSessionQueryPlugin, dict(path=':memory:'))
    try:
        tools = context.get('tools')
        before = tools.schemas()
        fiber = await context.plugin(ToolSessionQueryPlugin)
        names = {item['name'] for item in tools.schemas()}
        expected = {'session_search', 'session_event_search', 'session_trace', 'session_event_trace', 'session_event_read'}
        assert expected <= names
        prompt = context.get('systemPrompt')
        assert 'tool:session-query' in {item['name'] for item in (await prompt.assemble())['sections']}
        with pytest.raises(ToolArgsError) as failure:
            await tools.get_tool('session_event_read').execute(dict(seq='1'), SimpleNamespace())
        assert failure.value.message == 'invalid arguments: "seq" must be an integer'
        assert failure.value.code == 'INVALID_ARGS'
        assert failure.value.violations == ['"seq" must be an integer']
        await fiber.dispose()
        assert tools.schemas() == before
        assert 'tool:session-query' not in {item['name'] for item in (await prompt.assemble())['sections']}
        await context.plugin(ToolSessionQueryPlugin)
        assert expected <= {item['name'] for item in tools.schemas()}
    finally:
        await context.fiber.dispose()


@pytest.mark.parametrize('config', [dict(maxSearchResults=True), dict(maxSearchResults=0),
    dict(maxSearchResults=9007199254740992), dict(maxSearchResults=float('nan')),
    dict(searchTimeoutMs=2147483648), dict(searchTimeoutMs=1.5)])
def test_invalid_deployment_limits_are_refused(config):
    with pytest.raises(TypeError):
        resolve_config(config)


@pytest.mark.asyncio
@pytest.mark.parametrize('fails', [False, True])
async def test_caller_abort_wins_over_late_provider_result_and_drains(fails):
    entered, release = asyncio.Event(), asyncio.Event()
    controller = AbortController()
    reason = TypeError('caller cancellation')
    warnings, completed = [], []
    context = SimpleNamespace(logger=SimpleNamespace(warn=warnings.append))
    async def provider():
        entered.set()
        await release.wait()
        completed.append(True)
        if fails:
            raise SessionQueryError('private history path', 'SESSION_QUERY_INDEX_FAILED')
        return 'late result'
    pending = asyncio.create_task(boundary.call(context, controller.signal, 'search', provider))
    await entered.wait()
    controller.abort(reason)
    assert not pending.done()
    release.set()
    with pytest.raises(TypeError) as failure:
        await pending
    assert failure.value is reason
    assert completed == [True] and warnings == []


@pytest.mark.asyncio
async def test_preabort_never_invokes_or_logs_provider():
    controller = AbortController()
    reason = TypeError('already cancelled')
    controller.abort(reason)
    calls = []
    context = SimpleNamespace(logger=SimpleNamespace(warn=calls.append))
    with pytest.raises(TypeError) as failure:
        await boundary.call(context, controller.signal, 'search', lambda: calls.append('provider'))
    assert failure.value is reason and calls == []


@pytest.mark.parametrize('code', list(boundary.SAFE_FAILURES) + ['SESSION_QUERY_INVALID_CONFIG', 'SESSION_QUERY_SOURCE_CONFLICT', 'FOREIGN'])
def test_all_provider_failures_preserve_private_diagnostic_and_safe_model_message(code):
    warnings = []
    context = SimpleNamespace(logger=SimpleNamespace(warn=warnings.append))
    original = SessionQueryError('/secret/history.db private diagnostic', code)
    sanitized = boundary.sanitize_error(context, 'search', original)
    assert sanitized.code == (code if code in boundary.SAFE_FAILURES else 'SESSION_QUERY_TOOL_FAILED')
    assert sanitized.message == boundary.SAFE_FAILURES.get(code, 'session query operation failed')
    assert '/secret/history.db' not in sanitized.message
    assert len(warnings) == 1 and '/secret/history.db' in warnings[0]


def test_hostile_error_code_and_logging_fail_closed():
    class Hostile(SessionQueryError):
        @property
        def code(self):
            raise RuntimeError('private hostile code')
        @code.setter
        def code(self, value):
            pass
    context = SimpleNamespace(logger=SimpleNamespace(warn=lambda message: None))
    assert boundary.sanitize_error(context, 'search', Hostile('secret', 'PRIVATE')).code == 'SESSION_QUERY_TOOL_FAILED'
    def failing_log(message):
        raise RuntimeError('private logging failure')
    context.logger.warn = failing_log
    assert boundary.sanitize_error(context, 'search', SessionQueryError('secret', 'SESSION_QUERY_INDEX_FAILED')).code == 'SESSION_QUERY_TOOL_FAILED'


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['caller', 'other'])
async def test_title_observation_reauthorizes_exact_header_before_exposing_content(target):
    caller = dict(id='caller', header=dict(id='caller', cwd='/work'), events=[])
    async def snapshots(identities, signal):
        return [dict(sessionId=target, status='fulfilled', value=dict(session=dict(id=target, cwd='/outside'), title=dict(title='secret title')))]
    query = SimpleNamespace(readTitleSnapshots=snapshots)
    context = SimpleNamespace(get=lambda name: query, logger=SimpleNamespace(warn=lambda message: None))
    with pytest.raises(Exception) as failure:
        await workspace.read_title(context, caller, target, AbortController().signal)
    assert failure.value.code == 'SESSION_QUERY_TOOL_UNAUTHORIZED'
    assert 'secret title' not in failure.value.message


def test_deep_lineage_prunes_foreign_subtrees_without_recursion_or_hidden_ids():
    caller = dict(id='caller', header=dict(id='caller', cwd='/work'))
    node = dict(session=dict(header=dict(id='hidden', cwd='/outside')), descendants=[])
    for index in range(2500):
        node = dict(session=dict(header=dict(id='visible-' + str(index), cwd='/work')), descendants=[node])
    projected = workspace.authorize_descendants([node], caller)
    visited = list(workspace.visit_descendants(projected))
    assert len(visited) == 2501 and visited[-1] == (None, 2500)
    assert len(workspace.descendant_ids(projected)) == 2500


@pytest.mark.asyncio
async def test_search_deadline_reaches_authorization_and_waits_for_owned_cleanup():
    context = Context()
    await context.plugin(SessionPlugin)
    await context.plugin(SystemPrompt)
    await context.plugin(ToolsPlugin)
    await context.plugin(SqliteSessionQueryPlugin, dict(path=':memory:'))
    await context.plugin(ToolCallTimeoutPolicyPlugin)
    await context.plugin(ToolSessionQueryPlugin, dict(searchTimeoutMs=1))
    caller = context.get('sessions').create('caller', options=dict(meta=dict(cwd='/work')))
    aborted, release = asyncio.Event(), asyncio.Event()
    observed = []
    async def authorization(filters, signal):
        observed.append(signal)
        await signal.wait()
        aborted.set()
        await release.wait()
        return []
    context.get('sessionQuery').filterSessions = authorization
    signal = AbortController().signal
    pending = asyncio.create_task(context.get('tools').execute(ToolExecutionInput('deadline', 'session_search',
        dict(query='needle', parent_session_ids=['parent']), agent=SimpleNamespace(session=caller), signal=signal)))
    try:
        await asyncio.wait_for(aborted.wait(), 2)
        assert not pending.done() and observed[0] is not signal and not signal.aborted
        release.set()
        result = await pending
        assert result.is_error and result.error['info']['code'] == 'TOOL_TIMEOUT'
    finally:
        release.set()
        await pending
        await context.fiber.dispose()
