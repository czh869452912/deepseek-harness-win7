"""Compare the actual Source one-shot probe with native generation-owned I/O."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_mcp_negotiation_probe import normalize
PEER=URL=LOG=None


def cases():
    rows=[dict(mode=mode,options=opts) for mode in ('legacy','modern','none','loop','modern-loop') for opts in ({},{'maxPages':1},{'maxToolNames':1},{'maxPages':3,'maxToolNames':10})]
    rows.extend(dict(mode='legacy',options={key:value}) for key in ('timeoutMs','maxPages','maxToolNames') for value in (0,-1,True,'1',.5,9007199254740992))
    rows.extend([dict(mode='legacy',options={},binding='missing'),dict(mode='modern',options={},binding='present'),dict(mode='hold',options=dict(timeoutMs=100)),dict(mode='hold',options={},abort=True)])
    rows.extend(dict(mode=mode,options={},aggregate=True,cursor=cursor) for mode in ('legacy','modern','loop','modern-loop') for cursor in (False,True))
    return rows


def records():return [json.loads(line) for line in LOG.read_text(encoding='utf-8').splitlines()]


async def observe():
    from dsh.cordis.context import Context
    from dsh.core.abort import AbortController
    from dsh.mcp.server_probe_current import probe_server
    from dsh.mcp.client_current import CurrentSdkClient
    from dsh.mcp.generation_current import McpGeneration
    rows=[]
    for index,row in enumerate(cases()):
        ctx=Context();controller=AbortController();path='/native/'+str(index)+'/'+row['mode']
        ctx.set_service('credentials',type('Provider',(),{'resolve':lambda self,ref:dict(value='synthetic/token') if row.get('binding')=='present' else None})())
        config=dict(transport='streamable-http',serverName='inspect',url=URL+path,closeTimeoutMs=500,headers={})
        if 'binding' in row:config.update(expandTemplates=True,headers=dict(Authorization='Bearer ${credential:TOKEN}'))
        options=dict(row['options'],signal=controller.signal)
        try:
            async def run():
                if not row.get('aggregate'):return await probe_server(ctx,config,options)
                client=CurrentSdkClient('dsh-mcp-probe',input_required=row.get('clientOptions',{}).get('inputRequired'));generation=McpGeneration(client,500,str)
                try:
                    await generation.connect(config)
                    if row.get('direct'):
                        return dict(listing=await client.request(dict(method='tools/list'), row.get('requestOptions')))
                    return dict(listing=await client.listTools(dict(cursor='next') if row['cursor'] else None))
                finally:await generation.close()
            task=asyncio.create_task(run())
            if row.get('abort'):
                async def seen():
                    while not LOG.exists() or not any(item['path']==path and item['packet']['method']=='tools/list' for item in records()):await asyncio.sleep(.005)
                await asyncio.wait_for(seen(),5);controller.abort(RuntimeError('controlled abort'))
            result=await task
            if not row.get('aggregate'):assert type(result.pop('durationMs')) is int
        except Exception as error:result=dict(thrown=normalize(error))
        finally:await ctx.fiber.dispose()
        packets=[item['packet'] for item in records() if item['path']==path] if LOG.exists() else []
        # Timing/cancellation scheduling may change the cancellation notification.
        packets=[packet for packet in packets if packet['method']!='notifications/cancelled']
        budget=row['options'].get('timeoutMs')
        if type(budget) in (int,float) and (budget>2147483647 or 0<budget<1):
            packets='timing-dependent; raw log retained'
        rows.append(dict(case=row,result=result,packets=packets))
    return rows


def prepare(output):
    global PEER,URL,LOG
    LOG=output/'http-peer.jsonl'
    PEER=subprocess.Popen([sys.executable,str(ROOT/'scripts/oracles/rc022_mcp_server_probe_peer.py'),str(LOG)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    URL=PEER.stdout.readline().decode('utf-8').strip();assert URL.startswith('http://127.0.0.1:')
    path=output/'input.json';path.write_text(json.dumps(dict(url=URL,log=str(LOG),cases=cases())),encoding='utf-8');return [path]


def stop_peer():
    if PEER is None:return
    PEER.stdin.close();PEER.wait(timeout=10);assert PEER.returncode==0 and not PEER.stderr.read()
    PEER.stdout.close();PEER.stderr.close()


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_mcp_server_probe.mts','Actual Source probeServer and native generation-owned HTTP I/O: identity projection, paged listing, limits and loops, capability omission, credential resolution, whole-probe timeout and caller abort. Packet identity/metadata compared; durations excluded and nondeterministic cancellation notifications remain in retained raw logs.',[Path(__file__).resolve(),ROOT/'dsh/mcp/client_current.py',ROOT/'dsh/mcp/server_probe_current.py',ROOT/'scripts/oracles/rc022_mcp_server_probe_peer.py'],prepare=prepare)
    finally:stop_peer()
