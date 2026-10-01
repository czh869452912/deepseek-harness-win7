"""Host Inspect providers and first-valid-page routing over the original protocol."""
import asyncio
import inspect
from types import SimpleNamespace

from dsh.cordis.service import Service
from dsh.core.abort import NEVER_ABORTED, abort_reason_error
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.json_schema import assert_supported_json_schema, validate_json_schema_value
from dsh.core.session.json import FrozenDict, FrozenList, UNDEFINED, snapshot_json_value

_JS_SPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def js_trim(value):
    return value.strip(_JS_SPACE)


def _manifest(manifest):
    provider = manifest['id']
    if not js_trim(provider):
        raise ValueError('Cordis inspect provider id must not be empty')
    if not js_trim(manifest['description']):
        raise ValueError('Cordis inspect provider "{}" needs a description'.format(provider))
    names, methods = set(), []
    for method in manifest['methods']:
        name = method['name']
        if not js_trim(name):
            raise ValueError('Cordis inspect provider "{}" has an empty method name'.format(provider))
        if name in names:
            raise ValueError('Cordis inspect provider "{}" repeats method "{}"'.format(provider, name))
        if not js_trim(method['description']):
            raise ValueError('Cordis inspect method {}.{} needs a description'.format(provider, name))
        assert_supported_json_schema(method['inputSchema'])
        assert_supported_json_schema(method['outputSchema'])
        names.add(name)
        # The source freezes the manifest and method rows shallowly, preserving
        # the borrowed schema objects. Python's frozen containers adapt that.
        methods.append(FrozenDict(dict(method)))
    return FrozenDict(dict(manifest, methods=FrozenList(methods)))


def _method(manifest, name):
    found = next((method for method in manifest['methods'] if method['name'] == name), None)
    if found is None:
        raise ValueError('Cordis inspect provider "{}" has no method "{}"'.format(manifest['id'], name))
    return found


def _input(platform, provider, method, value):
    candidate = {} if value is UNDEFINED or value is None else value
    issues = validate_json_schema_value(method['inputSchema'], candidate, 'input')
    if issues:
        raise ValueError('{} Cordis inspect {}.{} rejected input: {}'.format(platform, provider, method['name'], '; '.join(issues)))


def _output(platform, provider, method, value):
    snapshot = snapshot_json_value(value, default=UNDEFINED)
    if snapshot is UNDEFINED:
        raise ValueError('{} Cordis inspect {}.{} returned a non-JSON value'.format(platform, provider, method['name']))
    issues = validate_json_schema_value(method['outputSchema'], snapshot, 'output')
    if issues:
        raise ValueError('{} Cordis inspect {}.{} returned invalid output: {}'.format(platform, provider, method['name'], '; '.join(issues)))
    return snapshot


def _throw_if_aborted(signal):
    if not aborted(signal):
        return
    raise abort_reason_error(signal)


class CordisInspectRegistryService(Service):
    def __init__(self, ctx):
        self._providers, self._pending = {}, {}
        self._client_manifest = None
        self._next_request = 1
        super().__init__(ctx, 'cordisInspect')
        ctx.effect(lambda: self.close, 'cordisInspect pending requests')

    def register(self, registration):
        manifest = _manifest(registration['manifest'])
        provider = manifest['id']
        if provider in self._providers:
            raise ValueError('Host Cordis inspect provider "{}" is already registered'.format(provider))
        stored = dict(registration, manifest=manifest)
        self._providers[provider] = stored
        def dispose():
            if self._providers.get(provider) is stored:
                del self._providers[provider]
        return dispose

    def sync_client_manifest(self, providers):
        ids, validated = set(), []
        for provider in providers:
            manifest = _manifest(provider)
            if manifest['id'] in ids:
                raise ValueError('Client Cordis inspect manifest repeats provider "{}"'.format(manifest['id']))
            ids.add(manifest['id'])
            validated.append(manifest)
        self._client_manifest = FrozenList(validated)

    def list(self):
        return [dict(manifest, platform=platform, methods=list(manifest['methods']))
            for platform, manifests in [('host', [provider['manifest'] for provider in self._providers.values()]),
                ('client', self._client_manifest or [])] for manifest in manifests]

    async def query(self, platform, provider, method_name, input, agent, signal):
        signal = NEVER_ABORTED if signal is None else signal
        if platform == 'host':
            registration = self._providers.get(provider)
            if registration is None:
                raise ValueError('Host Cordis inspect provider "{}" is not registered'.format(provider))
            method = _method(registration['manifest'], method_name)
            _input('Host', provider, method, input)
            _throw_if_aborted(signal)
            value = registration['query'](method_name, input, SimpleNamespace(agent=agent, signal=signal))
            if inspect.isawaitable(value):
                value = await value
            _throw_if_aborted(signal)
            return _output('Host', provider, method, value)
        return await self.query_client(provider, method_name, input, agent, signal)

    def resolve_client_query(self, agent, request_id, resolution):
        pending = self._pending.get(request_id)
        if pending is None or pending['request']['agentId'] != agent.id or not resolution.get('ok'):
            return dict(accepted=False)
        try:
            data = _output('Client', pending['request']['provider'], pending['method'], resolution.get('data', UNDEFINED))
        except Exception:
            return dict(accepted=False)
        del self._pending[request_id]
        pending['future'].set_result(dict(ok=True, data=data))
        self.ctx.emit('cordis/inspect-query-resolved', dict(requestId=request_id))
        return dict(accepted=True)

    def _cancel(self, request_id):
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        request = pending['request']
        pending['future'].set_result(dict(ok=False, reason='cancelled',
            message='Client inspect query {}.{} was cancelled'.format(request['provider'], request['method'])))
        self.ctx.emit('cordis/inspect-query-resolved', dict(requestId=request_id))

    async def query_client(self, provider_id, method_name, input, agent, signal):
        provider = next((row for row in self._client_manifest or [] if row['id'] == provider_id), None)
        if provider is None:
            raise ValueError('Client Cordis inspect provider "{}" is not registered'.format(provider_id))
        method = _method(provider, method_name)
        _input('Client', provider_id, method, input)
        _throw_if_aborted(signal)
        request_id = 'inspect-{}'.format(self._next_request)
        self._next_request += 1
        request = dict(requestId=request_id, agentId=agent.id, provider=provider_id, method=method_name)
        if input is not UNDEFINED:
            request['input'] = input
        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = dict(request=request, method=method, future=future)
        remove = subscribe_abort(signal, lambda *_: self._cancel(request_id))
        try:
            if aborted(signal):
                self._cancel(request_id)
            else:
                self.ctx.emit('cordis/inspect-query', request)
            resolution = await asyncio.shield(future)
            if not resolution['ok']:
                raise RuntimeError('{}.{}: {}'.format(provider_id, method_name, resolution['message']))
            return resolution['data']
        except asyncio.CancelledError:
            # Python callers can cancel their awaiter independently of a signal.
            # Retire that request, so late pages cannot claim abandoned work.
            self._cancel(request_id)
            raise
        finally:
            remove()

    def close(self):
        for request_id in list(self._pending):
            self._cancel(request_id)

    syncClientManifest = sync_client_manifest
    resolveClientQuery = resolve_client_query
    queryClient = query_client
