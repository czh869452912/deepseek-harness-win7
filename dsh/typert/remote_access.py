"""Resource-specific access decisions and live per-principal grant snapshots."""
import asyncio
import json
from types import SimpleNamespace as NS
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.core.session.json import UNDEFINED, FrozenDict, FrozenList
from dsh.typert.principal import principal_of
from dsh.typert.remote import Remote, TypertRemoteService
from dsh.typert.stores import field

REMOTE_ACCESS_SNAPSHOT_KEY = '__DSH_REMOTE_ACCESS__'
ALLOW = FrozenDict(kind='allow')
NO_ALLOW = FrozenDict(kind='deny', reason='no-allow')
POLICY_FAILED = FrozenDict(kind='deny', reason='policy-failed')


def same_resource(left, right):
    return left['kind'] == right['kind'] and left.get('id', UNDEFINED) == right.get('id', UNDEFINED)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


class _Follower:
    def __init__(self, principal):
        self.principal, self.dirty, self.wake = principal, False, None

    def touch(self):
        self.dirty = True
        if self.wake is not None and not self.wake.done():
            self.wake.set_result(None)

    async def changed(self, signal):
        def abort(*_):
            if self.wake is not None and not self.wake.done():
                self.wake.set_result(None)
        dispose = subscribe_abort(signal, abort)
        try:
            while not self.dirty and not signal.aborted:
                self.wake = asyncio.get_running_loop().create_future()
                await self.wake
                self.wake = None
        finally:
            dispose()
            self.wake = None
        self.dirty = False
        return not signal.aborted


class RemoteAccessService(TypertRemoteService):
    def __init__(self, ctx):
        super().__init__(ctx, 'remoteAccess')
        self.policies, self.reported, self.followers = {}, set(), set()
        self.lifetime = AbortController()
        ctx.effect(lambda: self.lifetime.abort, 'remoteAccess: snapshot generations')
        def web(child):
            child.on('webserver/index-inject', lambda table, peer: table.append(dict(
                kind='global', name=REMOTE_ACCESS_SNAPSHOT_KEY, value=self.snapshotFor(field(peer, 'principal')))))
        ctx.inject(['webServer'], web)

    def registerPolicy(self, kind, policy):
        if kind in self.policies:
            raise RuntimeError('remote access: principal kind %s already has a policy' % json.dumps(kind, ensure_ascii=False))
        entry = NS(kind=kind, policy=policy)
        def setup():
            self.policies[kind] = entry
            self.invalidate()
            def dispose():
                self.policies.pop(kind, None)
                self.invalidate()
            return dispose
        return self.ctx.effect(setup, 'remoteAccess.registerPolicy()')

    def invalidate(self, principal=UNDEFINED):
        self.reported.clear()
        key = UNDEFINED if principal is UNDEFINED else canonical_json(principal)
        for follower in list(self.followers):
            if key is UNDEFINED or canonical_json(follower.principal) == key:
                follower.touch()

    def decide(self, request):
        principal, action = request['principal'], request['action']
        if principal['kind'] == 'owner' or action == 'remoteAccess/follow':
            return ALLOW
        entry = self.policies.get(principal['kind'])
        if entry is None:
            return NO_ALLOW
        bindings = self._bindings(entry, principal, action)
        if bindings is UNDEFINED:
            return POLICY_FAILED
        for resource in request['resources']:
            evaluation, refusal = self._evaluate(entry, bindings, action, resource, request.get('args', UNDEFINED))
            if evaluation == 'failed':
                return POLICY_FAILED
            if evaluation == 'refuse':
                return self._explain(entry, request) if refusal is UNDEFINED else refusal
        return ALLOW

    def allows(self, resource):
        invocation = getattr(self.ctx, 'invocation', None)
        principal = principal_of(invocation)
        if invocation is None or principal is UNDEFINED:
            return True
        request = field(invocation, 'request')
        action = field(request, 'namespace') + '/' + field(request, 'method')
        entry = self.policies.get(principal['kind'])
        if entry is None:
            return False
        bindings = self._bindings(entry, principal, action)
        return bindings is not UNDEFINED and self._evaluate(entry, bindings, action, resource)[0] == 'allow'

    def snapshotFor(self, principal):
        if principal['kind'] == 'owner':
            return FrozenDict(type='baseline', owner=True)
        return dict(type='baseline', owner=False, grants=self._grants(principal))

    @Remote(dict(mode='stream'))
    async def follow(self, signal):
        signal.throwIfAborted()
        generation = AbortController()
        subscriptions = [subscribe_abort(source, generation.abort) for source in (signal, self.lifetime.signal)]
        follower = None
        try:
            principal = principal_of(getattr(self.ctx, 'invocation', None))
            if principal is UNDEFINED:
                yield self.snapshotFor(dict(kind='owner'))
                await generation.signal.wait_aborted()
                return
            follower = _Follower(principal)
            self.followers.add(follower)
            sent = self._grants(principal)
            yield dict(type='baseline', owner=False, grants=sent)
            while await follower.changed(generation.signal):
                next_grants = self._grants(principal)
                previous, sent = sent, next_grants
                for grant in next_grants:
                    before = next((other for other in previous if same_resource(other['resource'], grant['resource'])), None)
                    if before is None or before['actions'] != grant['actions']:
                        yield dict(type='upsert', grant=grant)
                for grant in previous:
                    if not any(same_resource(other['resource'], grant['resource']) for other in next_grants):
                        yield dict(type='remove', resource=grant['resource'])
        finally:
            self.followers.discard(follower)
            for dispose in subscriptions:
                dispose()

    def _bindings(self, entry, principal, purpose):
        try:
            return field(entry.policy, 'bindings')(principal)
        except Exception as error:
            self._report(entry, 'list bindings for ' + purpose, error)
            return UNDEFINED

    def _evaluate(self, entry, bindings, action, resource, args=UNDEFINED):
        refusal = UNDEFINED
        for binding in bindings:
            if not same_resource(binding['resource'], resource) or action not in binding['role']['actions']:
                continue
            condition = binding.get('condition', UNDEFINED)
            if condition is UNDEFINED:
                return 'allow', UNDEFINED
            request = dict(action=action, resource=resource)
            if args is not UNDEFINED:
                request['args'] = args
            try:
                decision = condition(request)
            except Exception as error:
                self._report(entry, 'evaluate a condition for ' + action, error)
                return 'failed', UNDEFINED
            if decision['kind'] == 'allow':
                return 'allow', UNDEFINED
            if refusal is UNDEFINED:
                refusal = decision
        return 'refuse', refusal

    def _explain(self, entry, request):
        try:
            explain = field(entry.policy, 'explain', UNDEFINED)
            reason = UNDEFINED if explain is UNDEFINED else explain(request)
        except Exception as error:
            self._report(entry, 'explain a refusal of ' + request['action'], error)
            return POLICY_FAILED
        return NO_ALLOW if reason is UNDEFINED else dict(kind='deny', reason=reason)

    def _grants(self, principal):
        entry = self.policies.get(principal['kind'])
        if entry is None:
            return []
        bindings = self._bindings(entry, principal, 'a snapshot')
        if bindings is UNDEFINED:
            return []
        grants, seen = [], []
        for binding in bindings:
            resource = binding['resource']
            if any(same_resource(other, resource) for other in seen):
                continue
            seen.append(resource)
            candidates = dict.fromkeys(action for other in bindings if same_resource(other['resource'], resource)
                for action in other['role']['actions'] if not action.startswith('event:'))
            actions = sorted(action for action in candidates if self._evaluate(entry, bindings, action, resource)[0] == 'allow')
            if actions:
                grants.append(FrozenDict(resource=resource, actions=FrozenList(actions)))
        return grants

    def _report(self, entry, action, error):
        if id(entry) in self.reported:
            return
        self.reported.add(id(entry))
        self.ctx.logger.warn('remote access: the %s policy failed to %s; its further failures are not logged until access state changes', json.dumps(entry.kind, ensure_ascii=False), action)
        self.ctx.logger.warn(error)
