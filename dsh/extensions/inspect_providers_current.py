"""Current process-owned Host inspect registrations; creative lifecycle is separate."""
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.plugin import Plugin
from dsh.core.cleanup import CleanupPromise
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_api_current import (RESOURCE, HOST_EVENTS,
    query_service_api, query_event_api)
from dsh.extensions.inspect_config_current import query_live_config


def _exact(input, key):
    value = input.get(key) if isinstance(input, dict) else None
    return value if type(value) is str else UNDEFINED


def host_inspect_providers(ctx):
    providers = []
    for template in RESOURCE['manifests']:
        manifest = dict(template, methods=[dict(method) for method in template['methods']])
        provider, method = manifest['id'], manifest['methods'][0]['name']
        def execute(requested, input, context, provider=provider, method=method):
            async def query():
                if requested != method:
                    raise ValueError('unknown {} inspect method "{}"'.format(provider, requested))
                if provider == 'Service':
                    return query_service_api(_exact(input, 'service'))
                if provider == 'Event':
                    return query_event_api(_exact(input, 'event'), HOST_EVENTS)
                if provider == 'Config':
                    return await query_live_config(ctx, input)
                return dict(tools=ctx.get('tools').schemas(context.agent))
            # Tool.query throws a wrong-method error before Promise.resolve.
            if provider == 'Tool' and requested != method:
                raise ValueError('unknown Tool inspect method "{}"'.format(requested))
            return CleanupPromise(start_coroutine(query()))
        providers.append(dict(manifest=manifest, query=execute))
    return providers


class CurrentCordisInspectProviders(Plugin):
    name = 'cordis-inspect-providers'
    inject = ['cordisInspect', 'tools']

    def apply(self, ctx):
        for provider in host_inspect_providers(ctx):
            ctx.effect(lambda provider=provider: ctx.cordisInspect.register(provider),
                       'cordis-inspect-providers: ' + provider['manifest']['id'])
