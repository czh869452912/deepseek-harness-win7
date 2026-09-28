"""Unforgeable same-process marker for the main AgentLoop request boundary."""
_MARKER = object()


class _AgentRequest(dict):
    pass


def mark_agent_loop_request(request):
    marked = _AgentRequest(request)
    marked._agent_marker = _MARKER
    return marked


def is_agent_loop_request(request):
    return getattr(request, "_agent_marker", None) is _MARKER
