"""Model-facing paths and synchronous sibling admission for named children."""
import json
import re
from types import SimpleNamespace
from dsh.core.session.json import UNDEFINED
from dsh.subagent.errors import SubagentError

ROOT_AGENT_NAME = 'lead'
_PATTERN = re.compile(r'[a-z][a-z0-9-]{0,31}')


def is_agent_name(value):
    return isinstance(value, str) and value != ROOT_AGENT_NAME and _PATTERN.fullmatch(value) is not None


def join_agent_path(parent_path, name):
    if parent_path is UNDEFINED or name is UNDEFINED:
        return UNDEFINED
    return name if parent_path == '' else parent_path + '/' + name


def agent_address(path, identity):
    return ROOT_AGENT_NAME if path == '' else identity if path is UNDEFINED else path


def parent_agent_path(path):
    return path.rsplit('/', 1)[0] if '/' in path else ''


class SiblingNameReservations:
    def __init__(self):
        # Strong identity ownership matches JS Map, including unhashable Python
        # agent fixtures. Release drops the exact parent once its pool is empty.
        self.pending = {}

    def reserve(self, parent, committed, requested=UNDEFINED):
        key = id(parent)
        record = self.pending.get(key)
        pending = record[1] if record is not None else set()
        if requested is UNDEFINED:
            ordinal = 1
            while 'agent-%s' % ordinal in committed or 'agent-%s' % ordinal in pending:
                ordinal += 1
            name = 'agent-%s' % ordinal
        else:
            encoded = json.dumps(requested, ensure_ascii=False, separators=(',', ':'))
            if not is_agent_name(requested):
                raise SubagentError('agent name %s is invalid; use 1-32 lower-case letters, digits, or hyphens starting with a letter, other than "lead"' % encoded, 'INVALID_AGENT_NAME')
            if requested in committed or requested in pending:
                raise SubagentError('agent name %s is already used by another subagent you created; choose another name' % encoded, 'DUPLICATE_AGENT_NAME')
            name = requested
        pending.add(name)
        self.pending[key] = (parent, pending)
        def release():
            pending.discard(name)
            current = self.pending.get(key)
            if not pending and current is not None and current[1] is pending:
                del self.pending[key]
        return SimpleNamespace(name=name, release=release)


isAgentName = is_agent_name
joinAgentPath = join_agent_path
agentAddress = agent_address
parentAgentPath = parent_agent_path
