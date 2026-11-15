"""Pair delegation snapshots, preset creation windows and structured input closure."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


class Execution:
    def __init__(self,parent=None):
        self.name='structured_output';self.parent=parent;self.token=object();self.concluded=0
    def concludeTurn(self):self.concluded+=1


async def observe():
    from dsh.subagent.child_agent import (child_session_meta,capture_delegated_policy_overrides,
        append_delegated_policy_overrides,apply_child_composition)
    from dsh.subagent.structured import attach_structured_runtime
    rows=[]
    for preset in (None,'workspace-write','auto','danger-full-access'):
        events=[]
        services=dict(permissionPresets=NS(current=lambda session:preset),sandboxPolicy=NS(overrideOf=lambda session:'workspace-write'),
                      approval=object(),agentPresets=NS(composedPreset=lambda ctx:'live-parent'))
        parent=NS(ctx=NS(get=services.get),session=NS(header=dict(id='parent',cwd='C:/work')))
        captured=capture_delegated_policy_overrides(parent)
        append_delegated_policy_overrides(NS(append=lambda name,value:events.append(dict(type=name,data=value))),captured)
        rows.append(dict(kind='policy',preset=preset,captured=captured,events=events,
            inherited=child_session_meta(parent,2,True),selected=child_session_meta(parent,2,False,'other')))
    for action in ('inherit','restore-host','selected','missing-preset'):
        trace=[]
        async def mount(ctx,preset):trace.append('mount:'+preset);await asyncio.sleep(0);trace.append('mounted')
        presets=NS(mount=mount,composeFrom=lambda *args:trace.append('inherit'))
        prompt=NS(context=lambda value:trace.append(dict(context=value)),section=lambda value:trace.append(dict(section=value)),
                  getContextOrder=lambda name:name,getSectionOrder=lambda name:name)
        services=dict(agentPresets=None if action=='missing-preset' else presets,systemPrompt=prompt,tools=NS(restrict=lambda value:trace.append(dict(restrict=value))))
        ctx=NS(get=services.get)
        composition=dict(persona='Historical',toolFilter=dict(deny=['secret']))
        if action in ('selected','missing-preset'):composition['agentPreset']='coding'
        row=dict(kind='composition',action=action)
        try:
            operation=apply_child_composition(ctx,None if action=='restore-host' else NS(ctx=object()),composition)
            row['async']=operation is not None
            if operation is not None:await operation
        except Exception as error:row['error']=dict(code=getattr(error,'code',None),message=str(error))
        row['trace']=trace;rows.append(row)
    for action in ('pending-input','direct-success','direct-error','nested-success','nested-error','invalid'):
        definition={};handlers={};guards=[]
        tools=NS(register=lambda value:definition.update(value),guard=guards.append)
        prompt=NS(section=lambda value:None,getSectionOrder=lambda value:0)
        services=dict(tools=tools,systemPrompt=prompt)
        ctx=NS(get=services.get,on=lambda event,callback:handlers.update({event:callback}))
        attachment=attach_structured_runtime(ctx,dict(type='object',properties=dict(ok=dict(type='boolean')),required=['ok'],additionalProperties=False),lambda:action!='pending-input')
        parent=object() if action.startswith('nested') else None
        execution=Execution(parent);states=[attachment.acceptsInput()];row=dict(kind='structured',action=action)
        try:await definition['execute'](dict(ok='wrong' if action=='invalid' else True),execution)
        except Exception:row['rejected']=True
        states.append(attachment.acceptsInput())
        if 'rejected' not in row:
            handlers['tools/result'](execution,NS(isError=action=='direct-error'))
            states.append(attachment.acceptsInput())
            row['guard']=guards[0](execution)
            if parent is not None:
                handlers['tools/result'](NS(name='run_code',token=parent),NS(isError=action=='nested-error'))
                states.append(attachment.acceptsInput())
        row.update(states=states,captured=attachment.captured(),concluded=execution.concluded)
        rows.append(row)
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_child_composition.mts','Captured permission preset and approval pin, inherited versus explicit preset composition, historical overrides and authoritative structured input closure including nested PTC rollback.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/child_agent.py',ROOT/'dsh/subagent/structured.py'])
