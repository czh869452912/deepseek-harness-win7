"""Candidate delegation preset and model authority, including explicit effort clearing."""
import copy
from dsh.core.session.json import UNDEFINED


def route_key(route):
    return route['provider']+'\0'+route['model']


def assert_allowed_routes(routes):
    if not isinstance(routes,list):raise RuntimeError('subagent model selection requires an array of routes')
    seen=set()
    for route in routes:
        if not isinstance(route,dict) or any(not isinstance(route.get(key),str) or not route[key] for key in ('provider','model')):
            raise RuntimeError('subagent model selection requires non-empty provider and model ids')
        key=route_key(route)
        if key in seen:raise RuntimeError('subagent model selection repeats route "%s/%s"' % (route['provider'],route['model']))
        seen.add(key)


def has_request(request):
    return any(request.get(key,UNDEFINED) is not UNDEFINED for key in ('provider','model','reasoning_effort'))


def assert_allowed_selection(policy,parent,route):
    allowed=(all(route[key]==parent.get(key,UNDEFINED) for key in ('provider','model')) if policy is UNDEFINED else
             any(all(candidate[key]==route[key] for key in ('provider','model')) for candidate in policy['routes']))
    if allowed:return
    raise RuntimeError('child LLM route "%s/%s" is not allowed for this Session%s' % (route['provider'],route['model'],
        '; without a recorded model-selection policy, explicit selection is limited to the parent route' if policy is UNDEFINED else ''))


def requested_options(configured,request,enabled,policy,parent):
    if not has_request(request):return configured
    if not enabled:raise RuntimeError('child model selection is disabled for this tool instance')
    for key in ('provider','model','reasoning_effort'):
        if request.get(key,UNDEFINED)=='':raise RuntimeError('child LLM `%s` must be non-empty' % key)
    if request.get('provider',UNDEFINED) is UNDEFINED or request.get('model',UNDEFINED) is UNDEFINED:
        raise RuntimeError('child LLM `provider` and `model` must be supplied together' if request.get('reasoning_effort',UNDEFINED) is UNDEFINED else
            'child LLM `reasoning_effort` requires both `provider` and `model`; supply both or omit all three fields')
    assert_allowed_selection(policy,parent,request)
    result={} if configured is UNDEFINED else dict(configured)
    return dict(result,provider=request['provider'],model=request['model'],reasoningEffort=request.get('reasoning_effort',UNDEFINED))


def has_configured_selection(options):
    return options is not UNDEFINED and any(options.get(key,UNDEFINED) is not UNDEFINED for key in ('provider','model','reasoningEffort'))


def coalesce(value,fallback):
    return fallback if value is UNDEFINED or value is None else value


async def preflight(llm,parent,requested,signal,inherit_effort=True):
    requested={} if requested is UNDEFINED else requested
    route={key:coalesce(requested.get(key,UNDEFINED),parent.get(key,UNDEFINED)) for key in ('provider','model')}
    if any(value is UNDEFINED for value in route.values()):
        raise RuntimeError('cannot select child LLM values without an effective provider and model')
    changed=any(route[key]!=parent.get(key,UNDEFINED) for key in route)
    effort=coalesce(requested.get('reasoningEffort',UNDEFINED),parent.get('reasoningEffort',UNDEFINED) if inherit_effort and not changed else UNDEFINED)
    if effort is not UNDEFINED:route['reasoningEffort']=effort
    await llm.resolveCallConfig(route,signal)


class SubagentPresetSelection:
    def __init__(self,config):
        self.config=config
        choices=self.choices
        if choices is UNDEFINED:return
        if len(set(choices))!=len(choices):raise RuntimeError('tool-subagent: allowedAgentPresets contains duplicate preset ids')
        if config.get('agentPreset',UNDEFINED) is not UNDEFINED and config['agentPreset'] not in choices:
            raise RuntimeError('tool-subagent: agentPreset must be included in allowedAgentPresets')

    @property
    def configured(self):
        return any(self.config.get(key,UNDEFINED) is not UNDEFINED for key in ('agentPreset','allowedAgentPresets'))

    @property
    def choices(self):return self.config.get('allowedAgentPresets',UNDEFINED)

    @property
    def description(self):
        default=self.config.get('agentPreset',UNDEFINED)
        fallback="Omit to inherit the parent agent's current preset." if default is UNDEFINED else 'Omit to use %s.' % default
        return 'Agent preset for this child. '+fallback

    def assertProvider(self,provider):
        if self.configured and (not provider.capabilities.get('agentPreset') or getattr(provider,'inheritsParentContext',False)):
            raise RuntimeError('tool-subagent: provider "%s" does not support independent agent preset selection' % provider.name)

    def resolve(self,request):
        identity=request.get('agent_preset',UNDEFINED)
        if identity is UNDEFINED:return self.config.get('agentPreset',UNDEFINED)
        if self.choices is UNDEFINED:raise RuntimeError('agent_preset selection is disabled for this tool instance')
        if not isinstance(identity,str) or identity not in self.choices:
            raise RuntimeError('agent_preset must be one of: '+', '.join(self.choices))
        return identity


def parse_policy(value):
    if value is None:return None
    if (not isinstance(value,list) or not value or any(not isinstance(route,dict) or set(route)!={'provider','model'}
            or any(not isinstance(route[key],str) or not route[key] for key in ('provider','model')) for route in value)):
        raise ValueError('invalid subagent model selection checkpoint')
    return copy.deepcopy(value)


def apply_policy(policy,event):
    if policy is not None or event['type']!='subagent/model-selection-policy':return policy
    allowed=event['data']['allowedModels'];assert_allowed_routes(allowed)
    if not allowed:raise RuntimeError('subagent/model-selection-policy requires at least one route')
    return allowed


POLICY=dict(key='subagentModelSelectionPolicy',stateVersion=1,stateSchema=parse_policy,
            init=lambda header,cut:None,apply=apply_policy)


def read_policy(handle,session):
    value=handle.stateOf(session)
    return UNDEFINED if value is None else [dict(route) for route in value]
