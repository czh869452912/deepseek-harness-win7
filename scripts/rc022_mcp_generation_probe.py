"""Pair actual generation task ownership and independent cleanup confirmation."""
import asyncio
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.mcp.generation_current import McpGeneration
    from dsh.mcp.diagnostic_current import describe_error
    rows=[]
    for mode in ('normal','no-close-event','close-throw','close-throw-after-event','local-unsettled','operation-timeout','connect-timeout','invalid-config'):
        events=[];held=asyncio.get_running_loop().create_future()
        class Client:
            transport=None
            async def connect(self,transport,options):
                self.transport=transport;await transport.start();events.append('started')
                if mode=='connect-timeout':await held
            async def close(self):
                events.append('close')
                if mode=='no-close-event':return
                if mode=='close-throw':raise RuntimeError('cleanup failed')
                await self.transport.close()
                if mode=='close-throw-after-event':raise RuntimeError('cleanup failed')
        client=Client();generation=McpGeneration(client,10,describe_error)
        config=dict(transport='streamable-http',url='::' if mode=='invalid-config' else 'http://127.0.0.1:1',headers={})
        try:await generation.connect(config,1 if mode=='connect-timeout' else 1000);connected=dict(ok=True)
        except Exception as error:connected=dict(error=describe_error(error))
        pending_outcome=None
        if mode in ('local-unsettled','operation-timeout'):
            async def work(signal):events.append('work-started');await held;events.append('work-finished');return 'late'
            pending=generation.run(work,1 if mode=='operation-timeout' else None)
            async def outcome():
                try:return dict(value=await pending)
                except Exception as error:return dict(error=describe_error(error))
            pending_outcome=asyncio.create_task(outcome())
            for _ in range(4):await asyncio.sleep(0)
            if mode=='operation-timeout':await pending_outcome
        before_pending=len(generation._pending)
        closing=generation.close();same_close=generation.close() is closing;result=await closing
        interrupted=await pending_outcome if pending_outcome is not None else None
        before_release=dict(pending=len(generation._pending),events=list(events))
        held.set_result(None)
        if client.transport is not None:await client.transport.close()
        for _ in range(16):await asyncio.sleep(0)
        repeated=await generation.close()
        assert generation._cleanup_work.done()
        rows.append(dict(mode=mode,connected=connected,beforePending=before_pending,sameClose=same_close,result=result,interrupted=interrupted,beforeRelease=before_release,afterPending=len(generation._pending),events=events,resultIdentity=result is repeated,repeatResult=repeated))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_generation.mts','Actual original McpGeneration against raw SDK HTTP start/close and controlled client/local-work lifetimes; native uses current raw HTTP start/close. Confirms deadline ownership, pending work after caller interruption, cleanup error precedence, transport closure independently of cleanup completion, shared cached close identity and late settlement. Supervisor integration remains separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/generation_current.py',ROOT/'dsh/mcp/deadline_current.py',ROOT/'dsh/mcp/transport_current.py',ROOT/'dsh/mcp/stdio_client.py',ROOT/'dsh/mcp/http_client.py'])
