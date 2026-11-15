"""rc.3 wire-to-Context registry and explicit Agent event forwarding."""
import json
from types import SimpleNamespace

from dsh.typert.registry import TypertRegistry
from dsh.typert.stores import ContextView, field, resolve_async
from dsh.typert.remote_events import RemoteEvents, lossless
from dsh.core.abort import AbortSignal
from dsh.typert.gateway import TypertGatewayService
from dsh.typert.api_remotes import ForwardedEventSource, ApiRemotesPlugin, EMIT_EVENTS
from dsh.typert.dispatch import RemoteDispatcher, TypertGatewayError
from dsh.typert.remote import remote_error_of, TypertLookupFailure
from dsh.typert.resource_registry import ResourceStore, ResourceView, ResourceLookupView


class CurrentContextView:
    registerHost = ContextView.registerHost
    registerClient = ContextView.registerClient
    configureHost = ContextView.configureHost
    getClient = ContextView.getClient
    subscribe = ContextView.subscribe

    def __init__(self, ctx, store):
        self.ctx, self.store = ctx, store

    def getHost(self, key):
        entry = self.store.hosts.get(key)
        if entry is None:
            return None
        adapter, resolver = entry['provider'], self.store.resolvers.get(key)
        if resolver is None:
            return adapter
        values = dict(wire=field(adapter, 'wire'), wireTypeSymbol=field(adapter, 'wireTypeSymbol'))
        if field(adapter, 'resource') is not None:
            values['resource'] = field(adapter, 'resource')
        return SimpleNamespace(**values, resolve=lambda identity: resolve_async(resolver['provider'], identity))


class CurrentTypertRegistry(TypertRegistry):
    def __init__(self, ctx):
        self.resource_store = ResourceStore()
        super().__init__(ctx)

    def _views(self, ctx):
        return dict(super()._views(ctx), contexts=CurrentContextView(ctx, self.context_store),
                    resources=ResourceView(ctx, self.resource_store), lookups=ResourceLookupView(ctx, self.lookup_store))


class CurrentRemoteEvents(RemoteEvents):
    def context_released_error(self):
        return RuntimeError('typert gateway: Remote event Agent Context was released')

    def cancelled_error(self, reason):
        if isinstance(reason, Exception):
            return reason
        error = RuntimeError('typert gateway: Remote event was cancelled')
        error.cause = reason
        return error

    def event_identity(self, source):
        identity = source['context'].get('agentId')
        if not isinstance(identity, str) or not identity:
            raise TypeError('typert gateway: scoped Remote events require a non-empty Agent identity')
        return dict(kind='agent', identity=identity)

    def project_request(self, source):
        request = source['request']
        if type(request) is not dict or 'agent' not in request or request['agent'] is not source['context']['subject']:
            raise TypeError('api gateway: Remote event request must carry its scoped Agent directly')
        signal = request.get('signal')
        if 'signal' in request and not isinstance(signal, AbortSignal):
            raise TypeError('api gateway: Remote event request signal must be an AbortSignal')
        projected = {key: value for key, value in request.items() if key not in ('agent', 'signal')}
        try:
            lossless(projected)
        except Exception:
            raise TypeError('api gateway: Remote event request is not lossless JSON data')
        return projected, signal


class CurrentRemoteDispatcher(RemoteDispatcher):
    async def prepare(self, request):
        try:
            return await super().prepare(request)
        except TypertGatewayError as error:
            error.name = 'TypertGatewayError'
            raise

    async def _resolve(self, provider, codec, value, wire, endpoint, kind, key=None):
        label = ('Context' if kind == 'context' else 'lookup') + ' provider ' + json.dumps(key)
        def failure(code, message, cause=None):
            error = TypertGatewayError(code, endpoint, label + message, wire)
            error.name, error.cause = 'TypertGatewayError', cause
            return error
        if provider is None:
            raise failure(kind + '-unavailable', ' is unavailable')
        if field(provider, 'wire') != wire or codec['mode'] == 'strict' and field(provider, 'wireTypeSymbol') != codec['typeSymbol']:
            raise failure('provider-mismatch', ' does not match its strict definition')
        try:
            resolved = await resolve_async(field(provider, 'resolve'), value)
        except Exception as error:
            if remote_error_of(error) is not None or isinstance(error, TypertLookupFailure):
                raise
            raise failure(kind + '-failed', ' failed', error) from error
        if resolved is None:
            raise failure(kind + '-not-found', ' did not resolve the requested identity')
        return resolved


class CurrentTypertGateway(TypertGatewayService):
    events_class = CurrentRemoteEvents
    dispatcher_class = CurrentRemoteDispatcher


class CurrentForwardedEventSource(ForwardedEventSource):
    emit_events = EMIT_EVENTS[:8] + ('goal/activation-changed',) + EMIT_EVENTS[8:]

    def event_context(self, event, request, subject):
        agent = request.get('agent')
        if agent is None or agent is not subject:
            raise TypeError('forwarded scoped event {} must carry its Agent directly'.format(json.dumps(event)))
        return dict(value=agent.ctx, subject=agent, agentId=agent.id)


class CurrentApiRemotes(ApiRemotesPlugin):
    source_class = CurrentForwardedEventSource
