"""Core lifecycle, scoped dispatch and durable request reconstruction checks.

Python's scoped Context is the regular event carrier; explicit scope_target
carriers are used by session and prompt services. Both carry opaque ScopeKey
identity, rather than treating the Agent object itself as the key.
"""
import json
import weakref

from dsh.cordis.plugin import Plugin
from dsh.core.scope import carrier_key_of, is_scope_carrier, scope_of
from dsh.core.session.json import FrozenDict, FrozenList
from dsh.diagnostics.invariants import registration_result
from dsh.llm.agent_request import is_agent_loop_request


def field(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


class AgentInvariant(Plugin):
    inject = ['invariants']

    def apply(self, ctx):
        def install(target, fail):
            statuses = weakref.WeakKeyDictionary()
            def observe(payload):
                agent, status = payload['agent'], payload['status']
                if statuses.get(agent) == status:
                    fail('agent/status repeated {} (no-op transition)'.format(status))
                statuses[agent] = status
            target.on('agent/status', observe, global_listener=True)
        return registration_result(ctx.get('invariants').register('@deepseek-ai/dsh-agent', install))


AGENT_EVENTS = frozenset('''agent/created agent/disposed agent/error agent/inbox/claimed
agent/inbox/discarded agent/inbox/inserted agent/pre-step agent/request agent/request-error
agent/session-start agent/status agent/turn-stopping approval/request goal/changed
tools/execute tools/post-execute tools/pre-execute tools/ptc-dispatch-log tools/result
user-questions/request'''.split())
PRESENCE_EVENTS = frozenset('session/created session/disposed session/event session/flush subagent/end subagent/start'.split())


class ScopeInvariant(Plugin):
    inject = ['invariants']

    def apply(self, ctx):
        def install(target, fail):
            def observe(mode, name, args, caller_ctx=None):
                if name not in AGENT_EVENTS and name not in PRESENCE_EVENTS and name != 'system-prompt/assemble':
                    return
                explicit = is_scope_carrier(caller_ctx)
                key = carrier_key_of(caller_ctx) if explicit else scope_of(caller_ctx)
                if not explicit and key is None:
                    fail('"{}" dispatched without a scope carrier'.format(name))
                if name in PRESENCE_EVENTS:
                    return
                if name == 'system-prompt/assemble':
                    expected = field(args[1], 'scope') if len(args) > 1 else None
                else:
                    agent = field(args[0], 'agent') if args else None
                    expected = scope_of(agent.ctx) if agent is not None else None
                if key is not expected:
                    fail('"{}" dispatched with a different subject scope'.format(name))
            target.on('internal/dispatch', observe, global_listener=True)
        return registration_result(ctx.get('invariants').register('@deepseek-ai/dsh-scope', install))


class AgentLoopInvariant(Plugin):
    inject = ['invariants']

    def apply(self, ctx):
        def install(target, fail):
            async def observe(options, next_fn):
                if not is_agent_loop_request(options):
                    return await next_fn()
                if not isinstance(options, FrozenDict) or not isinstance(options.get('messages'), FrozenList):
                    fail('a loop-built request and its messages must be frozen')
                session = target.get('sessions').get(options.get('sessionId'))
                if session is None:
                    fail('a loop-built request must carry a live session id')
                if not any(event['type'] == 'step/start' for event in session.events):
                    fail('a loop-built request with no step/start in its session log')
                header = session.request_header()
                if header is None:
                    fail('a loop-built request with no request/header event')
                encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                if encode(options['messages']) != encode(session.derive_messages()):
                    fail('llm request diverges from dispatch-time durable derivation')
                if (any(options.get(key) != header['config'].get(key) for key in ('model', 'temperature', 'maxTokens', 'stop'))
                    or options.get('system') != header.get('system')
                    or encode(options.get('tools', [])) != encode(header.get('tools', []))):
                    fail('llm request diverges from folded request header')
                return await next_fn()
            target.on('llm/stream', observe, global_listener=True, prepend=True)
        install.inject = ['sessions']
        return registration_result(ctx.get('invariants').register('@deepseek-ai/dsh-agent-loop', install))
