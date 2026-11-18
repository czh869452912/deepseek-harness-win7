"""Explicit old-domain unit models; these cannot qualify current Source.

Original Source facts stay in byte-preserved archive members. Native observers
execute the checkout's retained compatibility providers. Only observer metadata
is rebound in a derived unit model; no historical receipt is rewritten.
"""
import copy
import functools
import hashlib
import json
import os
from pathlib import Path

from release_gate_fixtures import historical_source, native_fixture


ROOT = Path(__file__).resolve().parents[1]
DOMAINS = frozenset(('agent-dependencies', 'ask-user', 'javascript-errors',
                     'message-values', 'subagent-model', 'tool-durable',
                     'tool-errors', 'unicode-carrier', 'canonical-llm',
                     'llm-metadata', 'llm-config', 'llm-prepared',
                     'deepseek-capture', 'deepseek-error', 'javascript-initial',
                     'javascript-ready', 'persistence-read', 'runtime-context',
                     'runtime-full-request', 'session-diagnostic', 'session-number',
                     'session-restore-sign'))

# Current production observations run independently in the current paired lane.
# These mappings identify successors, never transfer historical acceptance.
SUCCESSORS = {
    'runtime-context': ('rc022_agent_boundary', 'rc022_messages_wire'),
    'runtime-full-request': ('rc022_agent_registration', 'rc022_messages_adapter'),
    'session-diagnostic': ('rc022_session_admission', 'rc022_session_state'),
    'session-number': ('rc022_session_admission', 'rc022_session_composition'),
    'session-restore-sign': ('rc022_session_state', 'rc022_session_fork'),
    'javascript-initial': ('rc022_workflow_host', 'rc022_workflow_guest'),
    'javascript-ready': ('rc022_workflow_host', 'rc022_workflow_guest'),
    'persistence-read': ('rc022_sqlite_batch', 'rc022_session_access'),
    'llm-metadata': ('rc022_model_listing', 'rc022_model_discovery'),
    'llm-config': ('rc022_configured_model', 'rc022_request_extensions'),
    'llm-prepared': ('rc022_configured_model', 'rc022_messages_adapter'),
    'deepseek-capture': ('rc022_messages_wire', 'rc022_request_files', 'rc022_request_extensions'),
    'deepseek-error': ('rc022_messages_adapter', 'rc022_messages_framing'),
    'canonical-llm': ('rc022_messages_wire', 'rc022_messages_adapter',
                      'rc022_messages_framing', 'rc022_request_extensions'),
    'agent-dependencies': ('rc022_agent_registration', 'rc022_agent_boundary'),
    'ask-user': ('rc022_question_service', 'rc022_question_projection'),
    'javascript-errors': ('rc022_subprocess_errors', 'rc022_tool_pipeline'),
    'message-values': ('rc022_messages_wire', 'rc022_messages_framing'),
    'subagent-model': ('rc022_subagent_service', 'rc022_subagent_manager'),
    'tool-durable': ('rc022_tool_recovery', 'rc022_tool_updates'),
    'tool-errors': ('rc022_tool_pipeline', 'rc022_tool_admission'),
    'unicode-carrier': ('rc022_messages_wire', 'rc022_messages_adapter'),
}


def digest(value):
    return hashlib.sha256(value).hexdigest()


@functools.lru_cache(maxsize=None)
def _pair(name):
    if name not in DOMAINS:
        raise ValueError('Unreviewed historical domain model: ' + name)
    source = historical_source(name)
    native = native_fixture(name, source=source if name == 'deepseek-capture' else None)
    changes = {}
    if 'fixtureSha256' in native:
        observer = 'scripts/oracles/' + name.replace('-', '_') + '_python.py'
        current = digest((ROOT / observer).read_bytes())
        if native['fixtureSha256'] != current:
            raise ValueError('Historical domain observer bytes differ')
        changes[observer] = dict(original=source['inputs'][observer], model=current)
        source['inputs'][observer] = current
    if name == 'message-values':
        corpus = 'scripts/oracles/message-values-cases.json'
        current = (ROOT / corpus).read_bytes()
        # This historical member used CRLF; changing actual corpus content is
        # not authorized by this metadata translation and must fail.
        lf = current.replace(b'\r\n', b'\n')
        if source['casesSha256'] not in {digest(lf), digest(lf.replace(b'\n', b'\r\n'))}:
            raise ValueError('Historical message corpus content changed')
        if native['casesSha256'] != digest(current):
            raise ValueError('Historical message observer used another corpus')
        changes[corpus] = dict(original=source['casesSha256'], model=digest(current),
                               reason='Verified exact LF/CRLF variants of the same corpus')
        source['casesSha256'] = source['inputs'][corpus] = digest(current)
    destination = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
    if destination:
        folder = Path(destination) / 'historical-domain-models'; folder.mkdir(exist_ok=True)
        (folder / (name + '.json')).write_text(json.dumps(dict(
            scope='Historical compatibility unit model only; never current Source or release evidence',
            original_member='full-gate-root.zip!/' + name + '-paired.source.json',
            source_commit=source['sourceCommit'], node=source['node'], metadata_changes=changes,
            public_source_facts_changed=False), indent=2), encoding='utf-8')
    return source, native


def historical_pair(name):
    return copy.deepcopy(_pair(name))


def historical_identity(name, validator):
    def identity(source, *arguments, **options):
        expected = _pair(name)[0]
        if not isinstance(source, dict) or source.get('inputs') != expected['inputs']:
            raise ValueError('Historical domain model guarded bytes differ')
        # The archived input manifest is checked above. The original validator
        # still checks pin, Node, schemas and complete observations; reading the
        # current Source checkout here would confuse two different contracts.
        options['check_files'] = False
        return validator(source, *arguments, **options)
    return identity
