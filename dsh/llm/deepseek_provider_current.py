"""Current shared Host wiring and API-key-owned DeepSeek provider."""
import sys
import time

from dsh import __version__
from dsh.cordis.environment import launch_environment_of
from dsh.cordis.plugin import Plugin
from dsh.identity.anonymous_user_id import get_or_create_anonymous_user_id
from dsh.llm.deepseek_config_current import plainOptions, resolveAdapterOptions
from dsh.llm.deepseek_credentials import resolveDeepSeekApiKey, resolveDeepSeekAccountToken, rejectDeepSeekAccountToken
from dsh.llm.deepseek_messages_adapter import DeepSeekMessagesAdapter
from dsh.llm.deepseek_model_info_current import catalogModelInfo
from dsh.llm.deepseek_route_config import resolveApiKeyOptions, resolveAccountOptions, routeSchema
from dsh.llm.listed_catalog import resolveListedCatalog, refuseListedModel
from dsh.llm.llm_service import LlmError
from dsh.llm.model_listing import requestModelListing
from dsh.llm.model_listing_cache import ModelListingCache
from dsh.settings.provider import deep_equal_json
from dsh.typert.stores import field


def createModelListingCache(ctx, owner, provider, dependencies):
    tag = '['+owner+']'
    def diagnostic(message): print(tag, message, file=sys.stderr)
    cache = ModelListingCache(dict(dependencies, now=lambda: int(time.time()*1000), info=diagnostic, warn=diagnostic,
        changed=lambda: ctx.emit('llm/models-updated', provider)))
    ctx.effect(lambda: cache.dispose, owner+': model listing')
    return cache


def registerDeepSeekProvider(ctx, provider, dependencies):
    def settings(child): child.effect(lambda: child.settings.configure(dict(auto=False), ctx.fiber))
    ctx.inject(['settings'], settings)
    user = [None]; degraded = set(); omitted = set(); unaccepted = set()
    def user_id():
        if user[0] is None: user[0] = get_or_create_anonymous_user_id()
        return user[0]
    def access(attachments, ref):
        host = attachments.imageHostPath(ref)
        if host is None: return None
        fs = ctx.get('fs')
        path = fs.processPathFromHostPath(host) if fs is not None else None
        return None if path is None else dict(readonlyPath=path)
    def replay(event):
        route = event['provider']+'/'+event['model']; key = route+'\0'+event['reason']
        if key in degraded: return
        degraded.add(key)
        ctx.logger.warn('llm-deepseek: unusable Messages replay state on assistant history for route "'+route+
            '"; sending provider-neutral content ('+event['reason']+')')
    def serialization(event):
        route = event['provider']+'/'+event['model']
        if route in omitted: return
        omitted.add(route)
        ctx.logger.warn('llm-deepseek: sending route "'+route+'" without request extension fields '+', '.join(event['fields'])+
            ' because they failed to serialize: %o', event['error'])
    def acceptance(event):
        route = event['provider']+'/'+event['model']
        if route in unaccepted: return
        unaccepted.add(route)
        ctx.logger.warn('llm-deepseek: route "'+route+'" request extension acceptance failed; contributors resend on a later request: %o', event['error'])
    async def prepare(request):
        extensions = ctx.get('deepseekLlmApiExtensions')
        if extensions is not None: return await extensions.prepare(request)
        async def accept(): pass
        return dict(fields={}, accept=accept)
    adapter = DeepSeekMessagesAdapter(dict(dependencies, resolveUserId=user_id, onReplayDegrade=replay,
        onExtensionsOmitted=serialization, onExtensionsUnaccepted=acceptance,
        resolveAttachments=lambda: ctx.get('attachments'), resolveImageAccess=access, prepareExtensions=prepare))
    registration = ctx.llm.register_adapter([provider], adapter)
    ctx.effect(lambda: registration)
    ctx.effect(lambda: adapter.close, provider+': owned transport teardown')
    registered = [dependencies['options']()['retryPolicy']]
    def changed(*_):
        try: policy = dependencies['options']()['retryPolicy']
        except Exception as error:
            ctx.logger.warn(error); return
        if deep_equal_json(policy, registered[0]): return
        registration.replace([provider]); registered[0] = policy
    ctx.on('loader/volatile-update', changed)
    return adapter


class CurrentDeepSeekApiKeyProvider(Plugin):
    id = 'llm-deepseek-api-key'
    inject = ['llm']
    Config = routeSchema('apiKey')

    def apply(self, ctx):
        provider = 'deepseek-official'
        def options(): return resolveApiKeyOptions(plainOptions(self.config), launch_environment_of(ctx))
        options()
        async def resolve_key(connection):
            key = await resolveDeepSeekApiKey(ctx, connection['apiKeyEnv'])
            if key is not None: return key
            ref = connection['apiKeyEnv']
            raise LlmError('llm-deepseek: no API key for provider route "'+provider+'"; store '+ref+' through the credentials'
                +' service (the web Models page writes it), or export '+ref+' in the launching environment', 'MISSING_CREDENTIAL')
        async def present_key(connection):
            try: return await resolve_key(connection)
            except LlmError as error:
                if error.code == 'MISSING_CREDENTIAL': return None
                raise
        async def credential(_): return await present_key(options())
        def load(url, key, signal): return requestModelListing(url, {'x-api-key': key}, signal)
        listings = createModelListingCache(ctx, self.id, provider, dict(settings=lambda: options().get('listing'), credential=credential, load=load))
        reported = [None]
        def connection_of(connection, view):
            if view is None: return dict(connection, offered=connection['models'], refusals={}, badges={})
            listing = view.get('listing')
            catalog = resolveListedCatalog(dict(listing=listing['entries'] if listing is not None else None,
                supported=connection['models'], overrides={}, routeMaxTokens=connection['maxTokens'], clientVersion=__version__))
            if listing is not reported[0]:
                reported[0] = listing
                for problem in catalog['problems']: print('[llm-deepseek-api-key]', problem, file=sys.stderr)
            return dict(connection, models=catalog['resolution'], offered=catalog['offered'], refusals=catalog['refusals'], badges=catalog['badges'])
        def current_options():
            connection = options()
            return connection_of(connection, listings.current() if 'listing' in connection else None)
        async def connect(signal=None):
            connection = options()
            if 'listing' not in connection: return connection_of(connection, None)
            try: view = await listings.view(connection['listing'], signal)
            except Exception:
                if signal is not None and signal.aborted: raise
                return connection_of(connection, None)
            return connection_of(connection, view)
        async def auth(connection): return dict(headers={'x-api-key': await resolve_key(connection)})
        async def discover(route):
            connection = options()
            if 'listing' not in connection:
                if await present_key(connection) is None: return []
                return [catalogModelInfo(route, model) for model in connection['models']]
            view = await listings.view(connection['listing'])
            if not view['authenticated']: return []
            resolved = connection_of(connection, view)
            return [catalogModelInfo(route, model, resolved['badges'].get(model['id'])) for model in resolved['offered']]
        entry = getattr(ctx.fiber, 'entry', None)
        namespace = field(field(entry, 'options'), 'id') if entry is not None else None
        directory = ctx.llm.register_configurable_providers([dict(provider=provider, displayName='DeepSeek', settingsNs=namespace if namespace is not None else self.id, settingsPath=[])])
        ctx.effect(lambda: directory)
        self.adapter = registerDeepSeekProvider(ctx, provider, dict(providerName='DeepSeek', options=current_options,
            connect=connect, resolveAuth=auth, admit=lambda connection, model: refuseListedModel(model, connection['refusals'].get(model)), discoverModels=discover))
        following = ['listing' in options()]
        def changed(*_):
            try: next_following = 'listing' in options()
            except Exception: return
            if next_following != following[0]: listings.invalidate()
            following[0] = next_following
        ctx.on('loader/volatile-update', changed)


class CurrentDeepSeekAccountProvider(Plugin):
    id = 'llm-deepseek-account'
    inject = ['llm']
    Config = routeSchema('account')

    def apply(self, ctx):
        provider = 'deepseek-account'; environment = launch_environment_of(ctx)
        def settings(): return resolveAccountOptions(plainOptions(self.config), environment)
        settings(); supported = resolveAdapterOptions({})['models']
        async def auth(connection):
            token = await resolveDeepSeekAccountToken(ctx, connection['baseURL'])
            if token is None:
                raise LlmError('Sign in to DeepSeek to use the account provider. The request destination must allow account authentication.', 'ACCOUNT_SIGN_IN_REQUIRED')
            async def on_error(error):
                if not isinstance(error, LlmError): return error
                if error.code == 'QUOTA':
                    mapped = LlmError.fromFailure(dict(error.failure, code='ACCOUNT_QUOTA')); mapped.cause = error
                    return mapped
                if error.failure.get('status') != 401: return error
                mapped = LlmError.fromFailure(dict(error.failure, code='ACCOUNT_TOKEN_INVALID')); mapped.cause = error
                await rejectDeepSeekAccountToken(ctx, token)
                return mapped
            return dict(headers={'x-dsh-auth-token': token}, onRequestError=on_error)
        async def credential(url): return await resolveDeepSeekAccountToken(ctx, url)
        catalog = createModelListingCache(ctx, self.id, provider, dict(settings=lambda: settings()['catalog'], credential=credential,
            load=lambda url, token, signal: requestModelListing(url, {'x-dsh-auth-token': token}, signal)))
        logged = [None]
        def connection_of(view):
            resolved = settings(); listing = view.get('listing')
            result = resolveListedCatalog(dict(listing=listing['entries'] if listing is not None else None,
                supported=supported, overrides=resolved['modelOverrides'], routeMaxTokens=resolved['protocol']['maxTokens'], clientVersion=__version__))
            if listing is not logged[0]:
                logged[0] = listing
                for problem in result['problems']: print('[llm-deepseek-account]', problem, file=sys.stderr)
            return dict(resolved['protocol'], models=result['resolution'], catalog=result)
        owner_entry = getattr(ctx.fiber, 'entry', None)
        namespace = field(field(owner_entry, 'options'), 'id') if owner_entry is not None else None
        entry = dict(provider=provider, displayName='DeepSeek Account', settingsNs=namespace if namespace is not None else self.id, settingsPath=[])
        directory = ctx.llm.register_configurable_providers([entry]); ctx.effect(lambda: directory)
        reported = [None]
        def discovered(view):
            connection = connection_of(view)
            errors = connection['catalog']['overrideErrors']; error = '; '.join(errors) if errors else None
            if error != reported[0]:
                reported[0] = error
                directory.replace([entry if error is None else dict(entry, error=error)])
            return connection
        async def connect(signal=None): return connection_of(await catalog.view(settings()['catalog'], signal))
        async def discover(route):
            view = await catalog.view(settings()['catalog'])
            if not view['authenticated']: return []
            result = discovered(view)['catalog']
            return [catalogModelInfo(route, model, result['badges'].get(model['id'])) for model in result['offered']]
        self.adapter = registerDeepSeekProvider(ctx, provider, dict(providerName='DeepSeek Account',
            options=lambda: connection_of(catalog.current()), connect=connect, resolveAuth=auth,
            admit=lambda connection, model: refuseListedModel(model, connection['catalog']['refusals'].get(model)), discoverModels=discover))
