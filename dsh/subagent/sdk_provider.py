"""Fresh SDK provider; only route options cross the process boundary."""
import os
from types import MappingProxyType
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.session.json import UNDEFINED
from .out_of_process import NO_START_CAPABILITIES, assert_positive_finite, assert_usable_cwd
from .sdk_run import start_sdk_run, sdk_configuration_failure

SDK_START_CAPABILITIES = MappingProxyType(dict(NO_START_CAPABILITIES, agentOptions=True))


def resolve_sdk_route(config, requested=None):
    requested = {} if requested is None or requested is UNDEFINED else requested
    def get(key, fallback):
        value = requested.get(key, UNDEFINED)
        return config.get(fallback, UNDEFINED) if value is None or value is UNDEFINED else value
    result = dict(provider=get('provider', 'provider'), model=get('model', 'model'))
    effort = requested.get('reasoningEffort', UNDEFINED)
    if effort is not UNDEFINED:
        result['reasoningEffort'] = effort
    max_tokens = get('maxTokens', 'maxTokens')
    if max_tokens is not UNDEFINED:
        result['maxTokens'] = max_tokens
    return result


def resolve_configured_file(field, value):
    path = os.path.abspath(value)
    if not os.path.isfile(path):
        raise TypeError('subagent-dsh-sdk %s must name an existing file: %s' % (field, path))
    return path


class SdkSubagentProvider:
    capabilities = SDK_START_CAPABILITIES
    inheritsParentContext = False

    def __init__(self, ctx, config):
        self.ctx, self.config, self.name = ctx, config, config['providerName']
        self.agentRouteDefaults = MappingProxyType(dict(provider=config['provider'], model=config['model']))

    async def start(self, request):
        if request['signal'].aborted:
            raise RuntimeError('subagent request was aborted before the SDK child started')
        try:
            cwd = assert_usable_cwd('subagent-dsh-sdk', 'child cwd', request['cwd'])
        except Exception as error:
            self.ctx.logger.warn('subagent-dsh-sdk "%s": child start failed: %s', self.name, error)
            raise sdk_configuration_failure(error)
        spec = {key: self.config[key] for key in ('profile', 'patches', 'dshHome', 'env', 'shutdownTimeoutMs', 'disposeEofGraceMs', 'disposeGraceMs')}
        if 'dshBin' in self.config:
            spec['dshBin'] = self.config['dshBin']
        spec.update(cwd=cwd, originCwd=request['parent'].session.header.get('cwd'),
            onError=lambda error, reason: self.ctx.logger.warn('subagent-dsh-sdk "%s": child run failed (%s): %s', self.name, reason, error),
            **resolve_sdk_route(self.config, request.get('agentOptions')))
        return await start_sdk_run(request, spec)


class SubagentDshSdk(Plugin):
    id = 'subagent-dsh-sdk'
    inject = ['subagents']
    Config = Schema.object(dict(providerName=Schema.string().default('dsh-sdk'), dshBin=Schema.string(),
        profile=Schema.string().default('sdk'), patches=Schema.array(Schema.string()).default([]),
        dshHome=Schema.string().required(), provider=Schema.string().default('deepseek-official'),
        model=Schema.string().default('deepseek-v4-flash'), maxTokens=Schema.number().step(1).min(1).max(9007199254740991),
        env=Schema.dict(Schema.string()).default({}), shutdownTimeoutMs=Schema.number().default(1000),
        disposeEofGraceMs=Schema.number().default(6000), disposeGraceMs=Schema.number().default(3000)))

    def apply(self, ctx):
        config = dict(self.config)
        for name in ('shutdownTimeoutMs', 'disposeEofGraceMs', 'disposeGraceMs'):
            assert_positive_finite('subagent-dsh-sdk', name, config[name])
        if 'maxTokens' in config:
            value = config['maxTokens']
            if type(value) not in (int, float) or value <= 0 or value > 9007199254740991 or int(value) != value:
                raise TypeError('subagent-dsh-sdk maxTokens must be a positive safe integer')
        if not os.path.isabs(config['dshHome']):
            raise TypeError('subagent-dsh-sdk dshHome must be an absolute path')
        config['patches'] = [resolve_configured_file('patches[%s]' % index, value) for index, value in enumerate(config['patches'])]
        if 'dshBin' in config:
            config['dshBin'] = resolve_configured_file('dshBin', config['dshBin'])
        ctx.get('subagents').registerProvider(SdkSubagentProvider(ctx, config))
