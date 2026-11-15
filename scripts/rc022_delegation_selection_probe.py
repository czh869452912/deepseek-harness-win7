"""Pair model/preset authority and the own undefined effort override."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[]
    parent=dict(provider='p',model='m',reasoningEffort='high',maxTokens=100)
    for configured in (None,dict(maxTokens=32),dict(provider='q',model='other',reasoningEffort='low')):
        for request in ({},dict(provider='p',model='m'),dict(provider='p',model='m',reasoning_effort='low'),
                dict(provider='q',model='other'),dict(reasoning_effort='low'),dict(provider='p'),dict(model='m'),dict(provider='',model='m')):
            for policy in (None,dict(routes=[dict(provider='p',model='m'),dict(provider='q',model='other')])):
                rows.append(dict(kind='model',parent=parent,configured=configured,request=request,policy=policy,enabled=True))
    rows.append(dict(kind='model',parent=parent,configured=None,request=dict(provider='p',model='m'),policy=None,enabled=False))
    for requested in (None,{},dict(provider='q',model='other'),dict(provider='p',model='m',reasoningEffort=None),dict(reasoningEffort='low')):
        for inherit in (True,False):rows.append(dict(kind='preflight',parent=parent,requested=requested,inherit=inherit))
    rows.append(dict(kind='preflight',parent={},requested=None,inherit=True))
    for routes in (None,[],[dict(provider='p',model='m')],[dict(provider='p',model='m')]*2,
            [dict(provider='a\0b',model='c'),dict(provider='a',model='b\0c')],[dict(provider='',model='m')],
            [dict(provider='p',model='m',extra=True)]):
        rows.append(dict(kind='routes',routes=routes))
    for config in ({},dict(agentPreset='coding'),dict(allowedAgentPresets=['coding','review']),
            dict(agentPreset='coding',allowedAgentPresets=['coding','review']),dict(agentPreset='missing',allowedAgentPresets=['coding']),
            dict(allowedAgentPresets=['coding','coding'])):
        for request in ({},dict(agent_preset='review'),dict(agent_preset='invalid'),dict(agent_preset=None)):
            rows.append(dict(kind='preset',config=config,request=request))
    for value in (None,[],[dict(provider='p',model='m')],[dict(provider='p',model='m')]*2,
            [dict(provider='p',model='m',extra=True)],[dict(provider='',model='m')]):rows.append(dict(kind='checkpoint',value=value))
    return rows


async def observe():
    from dsh.core.session.json import UNDEFINED
    from dsh.subagent.selection import requested_options,has_request,has_configured_selection,preflight,assert_allowed_routes,SubagentPresetSelection,POLICY
    def plain(value):
        if value is UNDEFINED:return None
        return {key:item for key,item in value.items() if item is not UNDEFINED}
    rows=[]
    for case in cases():
        row=dict(kind=case['kind'])
        try:
            if case['kind']=='model':
                configured=case['configured'] if case['configured'] is not None else UNDEFINED
                value=requested_options(configured,case['request'],case['enabled'],case['policy'] if case['policy'] is not None else UNDEFINED,case['parent'])
                row.update(value=plain(value),same=value is configured,hasRequest=has_request(case['request']),
                    configured=has_configured_selection(configured),cleared=value is not UNDEFINED and value.get('reasoningEffort',None) is UNDEFINED)
            elif case['kind']=='preflight':
                calls=[]
                async def resolve(route,signal):calls.append(route)
                await preflight(NS(resolveCallConfig=resolve),case['parent'],UNDEFINED if case['requested'] is None else case['requested'],None,case['inherit'])
                row['calls']=calls
            elif case['kind']=='routes':assert_allowed_routes(case['routes']);row['accepted']=True
            elif case['kind']=='checkpoint':
                try:POLICY['stateSchema'](case['value']);row['accepted']=True
                except Exception:row['accepted']=False
            else:
                selection=SubagentPresetSelection(case['config'])
                row.update(configured=selection.configured,choices=None if selection.choices is UNDEFINED else selection.choices,description=selection.description)
                providers=[]
                for capable,inherits in ((True,False),(False,False),(True,True)):
                    try:selection.assertProvider(NS(name='test',capabilities=dict(agentPreset=capable),inheritsParentContext=inherits));providers.append(True)
                    except Exception:providers.append(False)
                row['providers']=providers
                value=selection.resolve(case['request']);row['value']=None if value is UNDEFINED else value
        except Exception as error:row['error']=str(error)
        rows.append(row)
    return rows


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_delegation_selection.mts','Exact model/preset selection authority, explicit undefined effort clearing, configured identity, preflight inheritance, route NUL-key collisions, strict checkpoint versus live route validation, independent preset capability and allowlists.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/selection.py',ROOT/'dsh/subagent/child_agent.py'],prepare=prepare)
