"""Named whole-tree discovery, relay, input wait and ancestor interruption."""
import copy
import json
from pathlib import Path
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.subagent.wait_input import InputWaits

DEFINITIONS=json.loads(Path(__file__).with_name('control_tool_definitions.json').read_text(encoding='utf-8'))


def quoted(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


class SubagentControlTools(Plugin):
    id='tool-subagent-control'
    inject=['tools','subagents','agents','systemPrompt']
    Config=Schema.object(dict(interrupt=Schema.boolean().default(True)))

    def apply(self,ctx):
        waits=InputWaits(ctx);definitions={}
        for metadata in DEFINITIONS['tools']:
            name=metadata['name']
            if name=='interrupt_agent' and not self.config['interrupt']:continue
            async def execute(args,execution,name=name):
                if name=='wait_agent':return await waits.execute(args,execution)
                caller=execution.agent
                if caller is None:raise RuntimeError(name+' requires a calling agent (exec.agent was undefined)')
                service=ctx.get('subagents')
                if name=='list_agents':
                    root=service.rootOf(caller)
                    entries=await service.listDescendants(root.id,execution.signal)
                    def status(identity):
                        agent=ctx.get('agents').get(identity)
                        return 'running' if agent is not None and agent.status=='running' else 'inactive'
                    result=[dict(name='lead',status=status(root.id),description='root agent')]
                    for entry in entries:
                        address=entry.get('path',entry['id'])
                        if entry['kind']=='diagnostic':result.append(dict(name=address,status=entry['reason']))
                        elif entry['mode']=='continuable':result.append(dict(name=address,status=status(entry['id']),description=entry['label']))
                    return result
                target=await service.resolveName(caller,args['agent'],execution.signal)
                if name=='send_message':
                    message_id=await service.sendMessage(caller,target,[dict(type='text',text=args['message'])],dict(signal=execution.signal))
                    return dict(messageId=message_id)
                service.interrupt(target,dict(kind='ancestor',agent=caller))
                return dict(accepted=True)
            def render(args,value,name=name):
                if name=='list_agents':
                    output='\n'.join('%s [%s]%s' % (entry['name'],entry['status'],
                        ' — '+entry['description'] if 'description' in entry else '') for entry in value)
                elif name=='send_message':output='message delivered to agent '+args['agent']
                elif name=='interrupt_agent':output='interrupt requested for agent '+args['agent']
                else:output=quoted(value)
                return [dict(type='text',text=output)]
            definition=dict(name=name,description=metadata['description'],parameters=copy.deepcopy(metadata['parameters']),execute=execute,
                output=dict(schema=copy.deepcopy(metadata['outputSchema']),render=render))
            if metadata['concurrencySafe']:definition['isConcurrencySafe']=lambda *_:True
            ctx.get('tools').register(definition)
            definitions[name]=ctx.get('tools').get_tool(name)
        def identity(context):
            agent=context.get('agent')
            if agent is None:return ''
            try:names=ctx.get('subagents').namesOf(agent)
            except Exception as error:
                if getattr(error,'name',None)!='SubagentError' or getattr(error,'code',None)!='UNAUTHORIZED':raise
                return 'Your agent id is %s. Your subagent tree root is unavailable. Continue independent work; subagent discovery and messaging require an active root.' % quoted(agent.id)
            if 'parent' not in names:result='You are the root agent. Your name is %s.' % quoted(names['self'])
            else:result='You are a subagent delegated by agent %s.\nYour name is %s.\nThe root agent of your collaboration tree is "lead".' % (quoted(names['parent']),quoted(names['self']))
            guidance=[]
            for name,text in (('send_message','To message other agents, use send_message({ agent: "<agent-name>", message: "..." }).'),
                              ('list_agents','Use list_agents({}) to find your collaborator agents and their names.')):
                if ctx.get('tools').get_tool(name,context.get('scope'),context.get('toolSet')) is definitions[name]:guidance.append(text)
            if guidance:result+='\n\n'+'\n'.join(guidance)
            return result
        prompt=ctx.get('systemPrompt')
        prompt.context(dict(name='subagent:identity',order=prompt.getContextOrder('SUBAGENT_DELEGATION'),required=True,interpolate=False,text=identity))
