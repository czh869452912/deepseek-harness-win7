"""Mounted current read-only Cordis tool observations."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[]
    for name in ['cordis_inspect_list','cordis_inspect_query']:
        for agent in [False,True]:
            for args in [{},dict(platform='host',provider='fixture',method='query'),dict(platform='client',provider='fixture',method='query',input=None),
                dict(platform='host',provider='fixture',method='query',input={'unicode':'中文','array':[False,1]}),dict(platform='other',provider='fixture',method='query')]:
                rows.append(dict(name=name,agent=agent,args=args))
    rows.append(dict(name='cordis_inspect_query',agent=True,args=dict(platform='host',provider='fixture',method='query'),failure=True))
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.extensions.inspect_tools_current import CurrentCordisInspectTools
    rows=[]
    for entry in cases():
        ctx=Context();calls=[]
        async def query(platform,provider,method,value,agent,signal):
            calls.append([platform,provider,method,'<undefined>' if value is UNDEFINED else value,agent.id,signal.aborted])
            if entry.get('failure'):raise ValueError('query failed')
            return dict(value=None if value is UNDEFINED else value)
        ctx.provide('cordisInspect',SimpleNamespace(list=lambda:[dict(id='fixture',platform='host',description='fixture',methods=[])],query=query))
        try:
            await ctx.plugin(CurrentSystemPrompt);await ctx.plugin(CurrentToolsPlugin);fiber=await ctx.plugin(CurrentCordisInspectTools)
            tool=ctx.tools.get(entry['name']);args=entry['args'];execution=SimpleNamespace(agent=SimpleNamespace(id='agent') if entry['agent'] else None,signal=AbortController().signal)
            row=dict(name=tool.name,description=tool.description,parameters=tool.parameters,output=tool.output['schema'],safe=not tool.validate_arguments(args) and tool.concurrency_classifier(args),calls=calls)
            presentation=tool.present_call(args)
            if presentation is not None:row['presentation']=presentation
            try:
                if tool.validate_arguments(args):row['error']='args'
                else:
                    value=await tool.handler(args,execution);row.update(value=value,render=tool.output['render'](args,value))
            except Exception as error:row['error']=str(error)
            await fiber.dispose();row['removed']=ctx.tools.get(entry['name']) is None;rows.append(row)
        finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_cordis_inspect_tools.mts',scope='Actual mounted Source/Native read-only Cordis tools and normalized descriptors; directory/query, agent requirement, omitted/null/structured input, errors, replay presentation and unregistration.',prepare=prepare,
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/extensions/inspect_tools_current.py',ROOT/'dsh/resources/cordis_inspect_tools_022.json'])
