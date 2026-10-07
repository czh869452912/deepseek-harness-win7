import asyncio,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dsh.cordis.context import Context
from dsh.llm.llm_service import LlmRuntime
from dsh.cordis.schema import ValidationError
from dsh.core.session import SessionPlugin
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin,CONFIGURED_AGENT_IDENTITIES_KEY
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
async def wait(check):
 async def poll():
  while not check():await asyncio.sleep(0)
 await asyncio.wait_for(poll(),3)
async def observe():
 rows=[]
 for mode in ['identity','invalid','missing','reload','overlap','cancel','deferred']:
  with tempfile.TemporaryDirectory() as root:
   ctx=Context();gate=asyncio.Event()
   try:
    await ctx.plugin(LlmRuntime)
    await ctx.plugin(SessionPlugin);await ctx.plugin(AgentPlugin)
    await ctx.plugin(SystemPrompt);await ctx.plugin(ToolsPlugin)
    if mode not in ['identity','invalid','deferred']:await ctx.plugin(JsonlSessionPersistencePlugin,{'root':root})
    agents=ctx.get('agents')
    if mode=='identity':
     ctx.provide(CONFIGURED_AGENT_IDENTITIES_KEY,{'main':{'id':'chosen','resume':False}})
     await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'main','sessionId':'ignored'},{'id':'other','sessionId':'unchanged'}]})
     rows.append(dict(mode=mode,chosen=agents.get('chosen') is not None,unchanged=agents.get('unchanged') is not None,ignored=agents.get('ignored') is not None))
    elif mode=='invalid':
     rejected=0;errors=[]
     for config,exception,message in [
      ([{'id':'a','sessionId':''}],ValidationError,'expected string length >= 1'),
      ([{'id':'a','sessionId':'s','resumeSessionId':'r'}],ValueError,'mutually exclusive'),
      ([{'id':'a','sessionId':'s'},{'id':'b','sessionId':'s'}],ValueError,'duplicate exact')]:
      try:await ctx.plugin(AgentLoopPlugin,{'agents':config})
      except exception as error:
       assert message in str(error)
       rejected+=1;errors.append('ValidationError' if isinstance(error,ValidationError) else 'Error')
     rows.append(dict(mode=mode,rejected=rejected,errors=errors,published=len(agents.list())))
    elif mode=='missing':
     failures=[];ctx.on('agent-loop/config-start-failed',lambda value:failures.append(value))
     await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'a','resumeSessionId':'missing'}]});await wait(lambda:failures)
     rows.append(dict(mode=mode,failed=failures[0]['sessionId'],published=len(agents.list()),stored=len(await ctx.get('sessionPersistence').list())))
    elif mode=='deferred':
     fiber=await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'a','resumeSessionId':'saved'}]})
     effect=next(e for e in fiber.get_effects() if e['label']=='agentLoop.resume(a)')
     rows.append(dict(mode=mode,children=[e['label'] for e in effect['children']],published=len(agents.list())))
    else:
     config={'agents':[{'id':'main','sessionId':'s','model':'mock'}]}
     first=await ctx.plugin(AgentLoopPlugin,config);await wait(lambda:agents.get('s'));old=agents.get('s')
     old.session.append('session/title',{'title':'remember'});await old.session.flush()
     if mode=='reload':await first.dispose()
     else:
      entered=asyncio.Event()
      async def cleanup():entered.set();await gate.wait()
      old.ctx.disposable(cleanup);disposal=asyncio.ensure_future(first.dispose());await entered.wait()
     second=await ctx.plugin(AgentLoopPlugin,config)
     if mode=='cancel':
      await second.dispose();gate.set();await disposal;rows.append(dict(mode=mode,published=len(agents.list())))
     else:
      retained=True
      if mode=='overlap':
       await asyncio.sleep(0);retained=agents.get('s') is old;gate.set();await disposal
      await wait(lambda:agents.get('s'));current=agents.get('s')
      rows.append(dict(mode=mode,retained=retained,replaced=current is not old,types=[e['type'] for e in current.session.events],history=any(e['type']=='session/title' and e['data']['title']=='remember' for e in current.session.events)))
      await second.dispose()
   finally:gate.set();await ctx.fiber.dispose()
 return rows
if __name__=='__main__':Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()),indent=2)+'\n',encoding='utf-8')
