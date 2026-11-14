"""Frozen V3 event vocabulary, independent of installed native event additions."""
RELEASED_V3_EVENT_TYPES = frozenset((
    'agent-preset/selected', 'agent/inbox/spliced', 'approval/asked', 'approval/decided', 'approval/policy',
    'assistant/attempt', 'assistant/message', 'command/done', 'command/run', 'compaction/end', 'compaction/prune',
    'compaction/start', 'compaction/summary', 'deliverables/presented', 'feedback/message-delete', 'feedback/message-put',
    'feedback/record', 'goal/change', 'hook/invoked', 'hook/result', 'image/offload', 'llm/retry', 'llm/retry-started',
    'model/selection', 'permission/preset', 'plan/mode', 'request/context', 'request/header', 'sandbox/mode',
    'schedule/change', 'session-log-deepseek/delivery-accepted', 'session/end-seed', 'session/title',
    'session/title-llm-request', 'step/end', 'step/start', 'subagent/catalog', 'subagent/descriptor',
    'subagent/model-selection-policy', 'system/message', 'team/member', 'team/message/delivered', 'team/message/queued',
    'team/task', 'todo/write', 'tool-workflow/agent-end', 'tool-workflow/agent-start', 'tool-workflow/run-end',
    'tool-workflow/run-start', 'tool/call', 'tool/ptc-dispatch', 'tool/ptc-dispatch-start', 'tool/result',
    'turn/end', 'turn/start', 'user/message', 'web/deepseek-search-llm-request', 'workspace/changes',
))


def namespaceV3OpaqueEvent(event):
    return dict(event, type='plugin:' + event['type'], ignorable=True) if (
        event.get('ignorable') is True and event['type'] not in RELEASED_V3_EVENT_TYPES) else event
