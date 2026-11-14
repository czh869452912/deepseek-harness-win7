"""Transform only declared message slots, preserving opaque payload identities."""
from dsh.core.session.json import UNDEFINED
from dsh.session.format import SessionFormatError


RENAMED_PRODUCERS = {
    'compact': 'compact-checkpoint', 'tools-code-mode': 'ptc-mode', 'tools-ptc': 'ptc-mode',
    'dsh-compaction-basic': 'compact-basic', '@deepseek-ai/dsh-system-prompt': 'runtime-context',
}
RELEASED_SAME_NAME_PRODUCERS = frozenset((
    'agent-instructions', 'session-reference', 'team-message', 'goal',
    'skill-invocation', 'skill-catalog', 'coordinator', 'subagent-report',
    'subagent-settled', 'webhook', 'agent-message', 'model-selection',
    'plan-mode', 'time-context', 'tmux-context', 'user-approval',
    'repeat-tool-reminder', 'tool-cordis', 'cordis-host-runner', 'tool-goal',
    'tool-jobs', 'hooks-codex', 'hooks-claude-code', 'schedule', 'dsh-session-title-llm',
))


def mapEventMessages(event, transform):
    data = event.get('data')
    if not isinstance(data, dict):
        return event
    kind = event['type']
    if kind == 'user/message':
        message = transform(data)
        return event if message is data else dict(event, data=message)
    if kind in ('developer/message', 'system/message', 'assistant/message', 'tool/result'):
        original = data.get('message')
        if not isinstance(original, dict):
            raise SessionFormatError(kind + ' requires a message')
        message = transform(original)
        return event if message is original else dict(event, data=dict(data, message=message))
    key = 'inserted' if kind == 'agent/inbox/spliced' else 'messages' if kind == 'session/title-llm-request' else None
    if key is None:
        return event
    messages = data.get(key)
    if not isinstance(messages, list):
        raise SessionFormatError(kind + ' requires message array')
    mapped = []
    for message in messages:
        if not isinstance(message, dict):
            raise SessionFormatError(kind + ' requires message objects')
        mapped.append(transform(message))
    if all(a is b for a, b in zip(mapped, messages)):
        return event
    return dict(event, data=dict(data, **{key: mapped}))


def rewritePluginSource(source, seq, role=UNDEFINED):
    plugin = source.get('plugin')
    if not isinstance(plugin, str):
        raise SessionFormatError('plugin source at seq {} is not canonical: plugin requires a string'.format(seq))
    if plugin == '@deepseek-ai/dsh-system-prompt' and role == 'system':
        kind = 'system-prompt'
    elif plugin in RENAMED_PRODUCERS:
        kind = RENAMED_PRODUCERS[plugin]
    elif plugin in RELEASED_SAME_NAME_PRODUCERS:
        kind = plugin
    else:
        kind = 'plugin:' + plugin
    if len(source) == 2:
        return dict(kind=kind)
    return {key: kind if key == 'kind' else item for key, item in source.items() if key != 'plugin'}


def rewriteV3MessageSource(source, seq, role=UNDEFINED):
    kind = source.get('kind')
    if not isinstance(kind, str) or not kind:
        raise SessionFormatError('message source at seq {} requires a nonempty kind'.format(seq))
    return rewritePluginSource(source, seq, role) if kind == 'plugin' else source
