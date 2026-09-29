"""Unforgeable same-process marker for the main AgentLoop request boundary."""
from dsh.core.session.json import FrozenDict, deep_freeze
_MARKER = object()


class _AgentRequest(FrozenDict):
    pass


def mark_agent_loop_request(request):
    marked = _AgentRequest(deep_freeze(request))
    marked._agent_marker = _MARKER
    return marked


def is_agent_loop_request(request):
    return getattr(request, "_agent_marker", None) is _MARKER
