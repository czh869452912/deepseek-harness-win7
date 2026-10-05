import math
from typing import Any

from dsh.cordis.schema import Schema
from dsh.settings.provider import install_settings_section
from dsh.settings.types import settings_namespace


DEFAULT_MAX_PARALLEL_TOOL_CALLS = 10
AGENT_LOOP_SETTINGS_NAMESPACE = settings_namespace('agent-loop')
AGENT_LOOP_SETTINGS_SCHEMA = Schema.object({
    'maxParallelToolCalls': Schema.number().step(1).min(1).default(DEFAULT_MAX_PARALLEL_TOOL_CALLS),
})
AGENT_LOOP_CONFIG_SCHEMA = Schema.object({
    'maxParallelToolCalls': Schema.number().step(1).min(1).default(DEFAULT_MAX_PARALLEL_TOOL_CALLS),
    'agents': Schema.array(Schema.object({
        'id': Schema.string().required(), 'sessionId': Schema.string().min(1),
        'provider': Schema.string(), 'model': Schema.string(), 'reasoningEffort': Schema.string().min(1),
        'maxTokens': Schema.number().step(1).min(1).max(9007199254740991),
        'cwd': Schema.string(), 'resumeSessionId': Schema.string(),
    })).default([]),
})


def resolve_max_parallel_tool_calls(value: Any = None) -> int:
    if value is None:
        return DEFAULT_MAX_PARALLEL_TOOL_CALLS
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('maxParallelToolCalls must be a positive integer')
    try:
        number = float(value)
    except OverflowError:
        raise ValueError('maxParallelToolCalls must be a positive integer') from None
    if not math.isfinite(number) or not number.is_integer() or number < 1:
        raise ValueError('maxParallelToolCalls must be a positive integer')
    return int(number)


def install_parallel_settings(ctx, owner, config):
    entry = {'maxParallelToolCalls': resolve_max_parallel_tool_calls(config.get('maxParallelToolCalls'))}
    owner._parallel_settings_source = lambda: entry
    install_settings_section(ctx, AGENT_LOOP_SETTINGS_NAMESPACE, AGENT_LOOP_SETTINGS_SCHEMA, entry, {
        'setSource': lambda source: setattr(owner, '_parallel_settings_source', source),
        'validate': lambda value: resolve_max_parallel_tool_calls(value['maxParallelToolCalls']),
        'onChange': lambda: None,
    })
