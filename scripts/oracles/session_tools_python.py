import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace


parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--root', type=Path)
options = parser.parse_args()
root = (options.root or Path(__file__).resolve().parents[2]).resolve()
sys.path.insert(0, str(root))
from dsh.cordis.context import Context
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController
from dsh.core.tools import ToolsService
from dsh.llm.error import HarnessError
from dsh.session.session_query import SessionQueryError, filter_session_results
from dsh.session import tool_query_input as tool_input
from dsh.session.tool_query import ToolSessionQueryPlugin
from dsh.session.tool_query import resolve_config
from dsh.session import tool_query_boundary as boundary
import dsh.session.tool_query as provider_module
MODULES = ['dsh/session/tool_query.py', 'dsh/session/tool_query_input.py', 'dsh/session/tool_query_boundary.py',
           'dsh/session/tool_query_workspace.py', 'dsh/session/tool_query_presentation.py', 'dsh/session/tool_query_operations.py',
           'dsh/core/tools.py']


async def main():
    rows = []
    async def observe(name, invoke):
        try:
            pending = invoke()
            value = await pending if hasattr(pending, '__await__') else pending
            rows.append(dict(name=name, value=value))
        except BaseException as error:
            rows.append(dict(name=name, error=dict(code=getattr(error, 'code', None), message=getattr(error, 'message', str(error)))))
    for index, query in enumerate(['\ufeff  needle\u00a0second\u2028', 'literal.* []', '\u001c', '  ', '\ufeff', 'bad\0query']):
        await observe('query-' + str(index), lambda: tool_input.normalize_query(query))
    instants = ['1970-01-01T00:00:00.0000001Z', '1969-12-31T23:59:59.9999999Z', '2026-07-24T00:00:00.12300001Z',
                '2026-07-24T08:00:00.1239999+08:00', '0000-02-29T00:00Z', '0099-12-31T23:59:59-23:59',
                '9999-12-31T23:59:59.99999999Z', '2000-02-29T00:00Z', '2100-02-29T00:00Z',
                '2026-02-30T10:00:00Z', '2026-01-01T24:00:00Z', '2026-01-01T00:00:00+24:00',
                '2026-07-24T10:00:00', '2026-07-24T10:00:00Z\n']
    for index, instant in enumerate(instants):
        await observe('timestamp-' + str(index), lambda: tool_input.build_session_filters(dict(query='q', created_at_from=instant, created_at_to=instant)))
    ranges = [('2026-07-24T00:00:00.1231Z', '2026-07-24T00:00:00.12311Z'),
              ('2026-07-24T00:00:00.12311Z', '2026-07-24T00:00:00.1231Z'),
              ('2026-07-24T00:00:00.1230000100Z', '2026-07-24T00:00:00.12300001Z'),
              ('1969-12-31T23:59:59.87600001Z', '1969-12-31T19:59:59.8769999-04:00')]
    for index, (lower, upper) in enumerate(ranges):
        await observe('range-' + str(index), lambda: tool_input.build_session_filters(dict(query='q', created_at_from=lower, created_at_to=upper)))
    records = [dict(header=dict(id='caller', version=2, createdAt=10, cwd='/work'), live=True, persisted=False),
               dict(header=dict(id='a', version=2, createdAt=100, cwd='/work', parentSession='hidden'), live=True, persisted=True),
               dict(header=dict(id='b', version=2, createdAt=101, cwd='/work'), live=False, persisted=True),
               dict(header=dict(id='hidden', version=2, createdAt=102, cwd='/outside'), live=True, persisted=False)]
    sections, calls, warnings = [], [], []
    controller = AbortController()
    signal = controller.signal
    scenario, page = '', 0
    def record(method, payload, provided):
        calls.append(dict(method=method, payload=payload, sameSignal=provided is signal))
    def hit(session_id):
        return dict(next(value for value in records if value['header']['id'] == session_id), bestMatch=dict(
            sessionId=session_id, seq=4, type='assistant/message', time=200, surface='current', snippet='needle excerpt'))
    target = dict(seq=1, time=200, type='user/message', data=dict(id='msg', role='user', content=[dict(type='text', text='first\nsecond')], source=dict(kind='user')))
    class Query:
        async def filterSessions(self, filters, provided):
            record('filterSessions', filters, provided)
            return filter_session_results(records, filters)
        async def searchSessions(self, request, execution):
            nonlocal page
            record('searchSessions', request, execution['signal'])
            if scenario == 'private-failure':
                raise SessionQueryError('private provider /secret/path', 'SESSION_QUERY_INDEX_FAILED')
            if scenario == 'foreign-failure':
                raise ThrownValueError(dict(code='SESSION_QUERY_INDEX_FAILED', toString=lambda: 'private foreign failure'))
            if scenario == 'repeated-cursor':
                return dict(items=[], nextCursor='same')
            if scenario == 'pages':
                page += 1
                if page == 1:
                    return dict(items=[hit('caller'), hit('hidden')], nextCursor='page-1')
                if page == 2:
                    return dict(items=[hit('a')], nextCursor='page-2')
                return dict(items=[hit('b'), hit('a')])
            return dict(items=[])
        async def searchEvents(self, request, execution):
            record('searchEvents', request, execution['signal'])
            return dict(session=records[0]['header'], items=[dict(sessionId='caller', seq=1, type='user/message', time=201, surface='current', snippet='needle')])
        async def readTitleSnapshots(self, session_ids, provided):
            record('readTitleSnapshots', session_ids, provided)
            return [dict(sessionId=session_id, status='fulfilled', value=dict(session=next(value for value in records if value['header']['id'] == session_id)['header']))
                    for session_id in session_ids]
        async def traceSession(self, session_id, provided):
            record('traceSession', session_id, provided)
            return dict(target=records[0], ancestors=[records[3]], complete=True, descendants=[
                dict(session=records[1], descendants=[dict(session=records[3], descendants=[dict(session=records[2], descendants=[])])]),
                dict(session=records[2], descendants=[])])
        async def traceEvent(self, request, provided):
            record('traceEvent', request, provided)
            return dict(session=records[0]['header'], target=dict(seq=1, type='user/message', time=200, surface='shadowed'),
                        replacedBy=4, replacementChain=[4, 6], replacedEventSeqs=[0], sourceEventSeqs=[0, 2], derivedEventSeqs=[3, 5])
        async def readEvent(self, request, provided):
            record('readEvent', request, provided)
            neighbor = dict(seq=2, time=300, type='assistant/message', data=dict(message=dict(
                id='reply', role='assistant', content=[dict(type='text', text='reply')])))
            return dict(session=records[0]['header'], target=target,
                        events=[dict(seq=0, time=100, type='step/start', data=dict(turn=1, step=1)), target, neighbor])
    owned = Context()
    tools = ToolsService(owned)
    services = dict(tools=tools, systemPrompt=SimpleNamespace(section=lambda section: sections.append(section)), sessionQuery=Query())
    ctx = SimpleNamespace(logger=SimpleNamespace(warn=warnings.append), get=services.get)
    ToolSessionQueryPlugin(config=dict(maxSearchResults=2, searchTimeoutMs=1234)).apply(ctx)
    names = [value['name'] for value in tools.schemas()]
    metadata = []
    for name in names:
        tool = tools.get_tool(name)
        metadata.append(dict(name=name, description=tool.description, parameters=tool.parameters, output=tool.output['schema'],
                             timeoutMs=tool.timeout_ms, concurrencySafe=tool.concurrency_classifier(dict(seq=1)) if tool.concurrency_classifier else None))
    rows.append(dict(name='registration', value=dict(sections=sections, tools=metadata)))
    execution = SimpleNamespace(signal=signal, agent=SimpleNamespace(session=SimpleNamespace(id='caller', header=records[0]['header'],
                                events=[dict(seq=0, type='turn/start'), dict(seq=1, type='user/message'), dict(seq=2, type='step/start')])))
    for name, tool_name, args in [
        ('empty', 'session_search', dict(query='q')), ('pages', 'session_search', dict(query='q')),
        ('private-failure', 'session_search', dict(query='q')), ('foreign-failure', 'session_search', dict(query='q')),
        ('repeated-cursor', 'session_search', dict(query='q')), ('prior-events', 'session_event_search', dict(query='needle')),
        ('empty-step-range', 'session_event_search', dict(query='q', seq_from=2)),
        ('unauthorized-before-query', 'session_event_search', dict(query=' ', session_id='hidden')),
        ('lineage', 'session_trace', {}), ('relationships', 'session_event_trace', dict(seq=1)),
        ('exact-read', 'session_event_read', dict(seq=1, before=1, after=1)),
        ('invalid-schema', 'session_event_read', dict(seq='1')), ('invalid-integer', 'session_event_trace', dict(seq=-1))]:
        scenario, page = name, 0
        calls.clear()
        warnings.clear()
        tool = tools.get_tool(tool_name)
        async def invoke():
            return dict(output=await tool.execute(args, execution), calls=list(calls))
        await observe(name, invoke)
        rows.append(dict(name=name + '-metadata', value=dict(calls=list(calls), warningPrivate=any('private' in message for message in warnings),
                         call=tool.present_call(args))))
    for index, code in enumerate(['SESSION_QUERY_ABORTED', 'SESSION_QUERY_CORRUPT_SESSION', 'SESSION_QUERY_EVENT_NOT_FOUND',
        'SESSION_QUERY_INDEX_FAILED', 'SESSION_QUERY_INVALID_CONFIG', 'SESSION_QUERY_INVALID_CURSOR', 'SESSION_QUERY_INVALID_FILTER',
        'SESSION_QUERY_INVALID_LIMIT', 'SESSION_QUERY_INVALID_QUERY', 'SESSION_QUERY_INVALID_LINEAGE', 'SESSION_QUERY_INVALID_SURFACE',
        'SESSION_QUERY_INVALID_WINDOW', 'SESSION_QUERY_PERSISTENCE_FAILED', 'SESSION_QUERY_SEARCH_DISABLED', 'SESSION_QUERY_SESSION_NOT_FOUND',
        'SESSION_QUERY_STALE_CURSOR', 'SESSION_QUERY_SOURCE_CONFLICT', 'FOREIGN_CODE']):
        warnings.clear()
        sanitized = boundary.sanitize_error(ctx, 'failure matrix', SessionQueryError('private provider diagnostic', code))
        rows.append(dict(name='failure-' + str(index), value=dict(code=sanitized.code, message=sanitized.message,
            privateLogged=any('private provider diagnostic' in message for message in warnings))))
    for index, config in enumerate([dict(maxSearchResults=0), dict(maxSearchResults=True), dict(maxSearchResults=9007199254740992),
        dict(searchTimeoutMs=2147483648), dict(searchTimeoutMs=1.5), dict(maxSearchResults=None, searchTimeoutMs=None)]):
        def validate():
            resolve_config(config)
            return 'accepted'
        await observe('config-' + str(index), validate)
    for fails in [False, True]:
        cancellation = AbortController()
        reason = HarnessError('caller cancellation', 'CALLER_CANCELLED')
        completed = []
        warnings.clear()
        async def provider():
            await asyncio.sleep(0)
            completed.append(True)
            cancellation.abort(reason)
            if fails:
                raise SessionQueryError('private late provider failure', 'SESSION_QUERY_INDEX_FAILED')
            return 'late result'
        async def cancelled():
            try:
                await boundary.call(ctx, cancellation.signal, 'pending provider', provider)
                return 'unexpected result'
            except BaseException as error:
                return dict(sameReason=error is reason, completed=bool(completed), warnings=list(warnings))
        await observe('abort-' + str(fails).lower(), cancelled)
    rows.append(dict(name='harness-error-kind', value=HarnessError('message', 'CODE').name))
    await owned.fiber.dispose()
    modules = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in MODULES}
    options.output.write_text(json.dumps(dict(root=str(root), python=sys.version.split()[0], moduleFile=provider_module.__file__, modules=modules, rows=rows), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


asyncio.run(main())
