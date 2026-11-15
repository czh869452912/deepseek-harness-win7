"""Real SDK stdio and model tool call into the user-question capability."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


async def main():
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.generate_agent_machine_current_cases import response
    from dsh.interaction.user_questions import UserQuestionsPlugin
    from dsh.interaction.tool_ask_user import ToolAskUserPlugin
    from dsh.sdk.plugin import SdkJsonRpcPlugin
    arguments=json.dumps(dict(questions=[dict(id='format',question='Which format?',options=[dict(label='CSV'),dict(label='JSON')])]))
    call=[dict(type='block-start',index=0,blockType='tool-call'),dict(type='tool-call-delta',index=0,id='question',name='ask_user_question',argumentsDelta=arguments),dict(type='block-end',index=0,block=dict(type='tool-call',id='question',name='ask_user_question',arguments=arguments)),dict(type='finish',reason=dict(kind='tool-calls'))]
    root=Path(sys.argv[1]);fixture=await setup(root/'sessions',script=[call,response('answered')],directory=root);ctx=fixture.ctx
    exited=asyncio.Event();ctx.set_service('appExit',lambda code:exited.set())
    try:
        await ctx.plugin(UserQuestionsPlugin);await ctx.plugin(ToolAskUserPlugin)
        await ctx.plugin(SdkJsonRpcPlugin);await exited.wait()
    finally:await ctx.fiber.dispose()


if __name__=='__main__':asyncio.run(main())
