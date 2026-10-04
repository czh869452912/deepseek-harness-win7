import math

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.session import tool_query_operations as operations
from dsh.session import tool_query_presentation as presentation


DEFAULT_MAX_SEARCH_RESULTS = 100
DEFAULT_SEARCH_TIMEOUT_MS = 30000
MAX_TIMER_DELAY_MS = 2147483647
PROMPT_TEXT = ('Use session_search to find relevant work from prior sessions, or session_event_search to search earlier '
               'events in one session. Search results are cursor-free and workspace-scoped. Follow a useful hit with '
               'session_trace, session_event_trace, or session_event_read when you need lineage, relationships, or exact data.')


def field(kind, description, **values):
    return dict(type=kind, description=description, **values)


def parameters(properties, required=()):
    result = dict(type='object', properties=properties)
    if required:
        result['required'] = list(required)
    return result


SESSION_SEARCH_PARAMETERS = parameters({
    'query': field('string', 'Literal full-text query over prior session history.'),
    'session_ids': field('array', 'Optional session ids to include.', items=dict(type='string')),
    'created_at_from': field('string', 'Inclusive timezone-qualified ISO 8601 creation-time lower bound.'),
    'created_at_to': field('string', 'Inclusive timezone-qualified ISO 8601 creation-time upper bound.'),
    'parent_session_ids': field('array', 'Optional direct parent session ids.', items=dict(type='string')),
    'include_root_sessions': field('boolean', 'Include sessions with no parent in the parent filter.'),
    'availability': field('array', 'Require at least one selected source availability.', items=dict(type='string', enum=['live', 'persisted'])),
    'event_seq_from': field('integer', 'Inclusive event sequence lower bound.'),
    'event_seq_to': field('integer', 'Inclusive event sequence upper bound.'),
    'event_time_from': field('string', 'Inclusive timezone-qualified ISO 8601 event-time lower bound.'),
    'event_time_to': field('string', 'Inclusive timezone-qualified ISO 8601 event-time upper bound.'),
    'event_types': field('array', 'Event types to include.', items=dict(type='string')),
    'event_surfaces': field('array', 'Event surfaces to include.', items=dict(type='string', enum=['current', 'shadowed', 'log-only'])),
}, ['query'])
EVENT_SEARCH_PARAMETERS = parameters({
    'session_id': field('string', 'Target session id. Omit for the current session.'),
    'query': field('string', 'Literal full-text query over the target session.'),
    'seq_from': field('integer', 'Inclusive event sequence lower bound.'),
    'seq_to': field('integer', 'Inclusive event sequence upper bound.'),
    'time_from': field('string', 'Inclusive timezone-qualified ISO 8601 event-time lower bound.'),
    'time_to': field('string', 'Inclusive timezone-qualified ISO 8601 event-time upper bound.'),
    'event_types': field('array', 'Event types to include.', items=dict(type='string')),
    'surfaces': field('array', 'Event surfaces to include.', items=dict(type='string', enum=['current', 'shadowed', 'log-only'])),
}, ['query'])
TARGET_PROPERTIES = dict(session_id=field('string', 'Target session id. Omit for the current session.'))


def resolve_config(config):
    maximum = config.get('maxSearchResults')
    timeout = config.get('searchTimeoutMs')
    maximum = DEFAULT_MAX_SEARCH_RESULTS if maximum is None else maximum
    timeout = DEFAULT_SEARCH_TIMEOUT_MS if timeout is None else timeout
    if type(maximum) not in (int, float) or not 1 <= maximum <= 9007199254740991 or not math.isfinite(maximum) or int(maximum) != maximum:
        raise TypeError('tool-session-query: maxSearchResults must be a positive safe integer')
    if type(timeout) not in (int, float) or not 1 <= timeout <= MAX_TIMER_DELAY_MS or not math.isfinite(timeout) or int(timeout) != timeout:
        raise TypeError('tool-session-query: searchTimeoutMs must be a positive integer no greater than 2147483647')
    return int(maximum), int(timeout)


class ToolSessionQueryPlugin(Plugin):
    id = 'tool-session-query'
    name = '@deepseek-ai/dsh-tool-session-query'
    inject = ['tools', 'systemPrompt', 'sessionQuery']
    Config = Schema.object(dict(
        maxSearchResults=Schema.number().step(1).min(1).default(DEFAULT_MAX_SEARCH_RESULTS),
        searchTimeoutMs=Schema.number().step(1).min(1).max(MAX_TIMER_DELAY_MS).default(DEFAULT_SEARCH_TIMEOUT_MS),
    ))

    def apply(self, ctx):
        maximum, timeout = resolve_config(self.config)
        ctx.get('systemPrompt').section(dict(name='tool:session-query', order=2300, text=PROMPT_TEXT))
        async def session_search(args, execution):
            return await operations.execute_session_search(ctx, args, execution, maximum)
        async def event_search(args, execution):
            return await operations.execute_event_search(ctx, args, execution, maximum)
        async def session_trace(args, execution):
            return await operations.execute_session_trace(ctx, args, execution)
        async def event_trace(args, execution):
            return await operations.execute_event_trace(ctx, args, execution)
        async def event_read(args, execution):
            return await operations.execute_event_read(ctx, args, execution)
        target_sequence = dict(TARGET_PROPERTIES, seq=field('integer', 'Target event sequence number.'))
        read_properties = dict(target_sequence,
                               before=field('integer', 'Number of preceding raw events to summarize. Omit for none.'),
                               after=field('integer', 'Number of following raw events to summarize. Omit for none.'))
        definitions = [
            dict(name='session_search', description='Search prior sessions in the caller workspace and return the strongest matching event from each session.',
                 parameters=SESSION_SEARCH_PARAMETERS, timeoutMs=timeout, execute=session_search,
                 presentCall=lambda args: presentation.present_search_call(True, args)),
            dict(name='session_event_search', description='Search prior events in one authorized session; the current session excludes the step performing this call.',
                 parameters=EVENT_SEARCH_PARAMETERS, timeoutMs=timeout, execute=event_search,
                 presentCall=lambda args: presentation.present_search_call(False, args)),
            dict(name='session_trace', description='Read the authorized session lineage around one session, including complete visible ancestor and descendant relationships.',
                 parameters=parameters(TARGET_PROPERTIES), execute=session_trace, isConcurrencySafe=lambda args: True,
                 presentCall=presentation.present_session_trace_call),
            dict(name='session_event_trace', description='Read every direct replacement and relationship to a cited source event for one event in an authorized session.',
                 parameters=parameters(target_sequence, ['seq']), execute=event_trace, isConcurrencySafe=lambda args: True,
                 presentCall=lambda args: presentation.present_event_target_call('Trace event', args)),
            dict(name='session_event_read', description='Read one full unabridged event and optional neighboring raw-event summaries from an authorized session.',
                 parameters=parameters(read_properties, ['seq']), execute=event_read, isConcurrencySafe=lambda args: True,
                 presentCall=lambda args: presentation.present_event_target_call('Read event', args)),
        ]
        for definition in definitions:
            definition['output'] = dict(schema=dict(type='string'), render=lambda args, value: [dict(type='text', text=value)])
            ctx.get('tools').register(definition)
