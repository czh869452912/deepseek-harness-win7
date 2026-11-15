"""Command definition identity and SDK input admission observations."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from scripts.rc022_subagent_fixture import setup
    from dsh.interaction.commands_current import CurrentCommandRuntime
    from dsh.interaction.command_builtin import BUILTINS, builtin_command_name, resolve_command
    from dsh.sdk.query_input import query_command, query_content, query_command_images
    fixture=await setup(WORKSPACE/'native',script=[]);ctx=fixture.ctx;rows=[]
    try:
        await ctx.plugin(CurrentCommandRuntime)
        parent=await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')))
        async def handler(_):return dict(kind='success')
        for kind,name in [('goal','wish'),('compact','compress'),('permission','access'),('plan','design'),('feedback','feedback'),('export','archive')]:ctx.commands.register(dict(name=name,description=kind,definitionId=BUILTINS[kind],handler=handler))
        ctx.commands.register(dict(name='goal',description='third-party',handler=handler))
        catalog=ctx.commands.list(parent.agent)
        rows.append(dict(name='catalog',value=[descriptor.to_dict() for descriptor in catalog]))
        for token in ('goal','目标','wish','compact','压缩','compress','permission','权限','access','plan','计划','design','feedback','export','missing'):
            descriptor=resolve_command(token,catalog)
            rows.append(dict(name='resolve',token=token,value=None if descriptor is None else dict(name=descriptor.name,builtin=builtin_command_name(descriptor))))
            for separator in ('',' ','\t','\v','\u00a0','\u0085','\ufeff','\u2028'):
                for tail in ('','arg'):
                    text='/'+token+separator+tail
                    rows.append(dict(name='route',text=text,value=query_command(text,catalog)))
        inputs=[None,[],[None],[{}],[dict(type=3)],[dict(type='text')],[dict(type='text',text='a',extra=1)],[dict(type='text',text=' \ufeff')],[dict(type='text',text='hello')],[dict(type='image',data='AA==',mimeType='image/png',name='x')],[dict(type='image',data=3,mimeType='image/png')],[dict(type='image',data='AA==',mimeType='text/plain')],[dict(type='image',attachment={})],[dict(type='image',attachment=[])],[dict(type='custom',data=1)]]
        for value in inputs:
            try:result=dict(value=query_content(value))
            except Exception as error:result=dict(error=str(error))
            rows.append(dict(name='content',input=value,result=result))
        text=dict(type='text',text='/plan');image=dict(type='image',data='AA==',mimeType='image/png')
        for blocks in [[text],[image,text,image],[text,dict(text)],[text,dict(type='image',attachment={})],[text,dict(type='custom')]]:
            try:result=dict(value=query_command_images(blocks,text))
            except Exception as error:result=dict(error=str(error))
            rows.append(dict(name='images',blocks=blocks,result=result))
        return rows
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_input.mts','Actual command registries preserve optional definitionId in immutable descriptors; Source/native builtin aliases and exact-name priority compare renamed registrations plus third-party shadow. SDK routes compare ECMAScript whitespace, content admission and exact text-block identity for command image extraction; no command execution.',[Path(__file__).resolve(),ROOT/'dsh/interaction/commands.py',ROOT/'dsh/interaction/command_builtin.py',ROOT/'dsh/sdk/query_input.py'],prepare=prepare)
