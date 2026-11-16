"""Observe original and native supervisors over actual controlled HTTP wires."""
import asyncio
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe, rc022_mcp_server_probe_probe as peer
CASES=['legacy','modern','none','startup-timeout','credentials','reconnect-budget','registration-conflict','tool-cleanup-error']


def config_cases():
    patches=[{},dict(startupTimeoutMs=1),dict(startupTimeoutMs=0),dict(startupTimeoutMs=2147483648),
        dict(closeTimeoutMs=1.5),dict(closeTimeoutMs=0),dict(closeTimeoutMs=2147483648),
        dict(expandTemplates=True),dict(expandTemplates='false'),dict(maxInstructionBytes=0),dict(maxInstructionBytes=1.5)]
    return [dict(dict(transport=kind,serverName='configured',**(dict(command='controlled') if kind=='stdio' else dict(url='http://127.0.0.1:1'))),**patch) for kind in ('stdio','streamable-http') for patch in patches]


def normalized(value):
    if isinstance(value,list):return [normalized(item) for item in value]
    if isinstance(value,dict):return {key:(0 if key in ('connectedAt','nextRetryAtMs') else normalized(item)) for key,item in value.items()}
    return value


async def observe():
    from dsh.cordis.context import Context
    from dsh.mcp.connection import resolve_reconnect_policy
    from dsh.mcp.connection_current import SupervisedMcpConnection
    from dsh.mcp.status_current import McpStatusCell
    from dsh.mcp.diagnostic_current import describe_error
    from dsh.mcp.current import RESOURCE_CONFIG
    rows=[]
    for index,mode in enumerate(CASES):
        ctx=Context();names=set();trace=[];values={};logs=[]
        for level in ('info','warn','error'):
            setattr(ctx.logger,level,lambda *args,level=level:logs.append(dict(level=level,message=str(args[0]))))
        def register(spec):
            name=spec['name']
            if name in names:raise RuntimeError('occupied')
            names.add(name)
            def dispose():
                names.discard(name)
                if mode=='tool-cleanup-error':raise RuntimeError('cleanup synthetic/token')
            return dispose
        ctx.set_service('tools',type('Registry',(),{'register':staticmethod(register)})())
        ctx.set_service('credentials',type('Provider',(),{'resolve':lambda self,ref:dict(value=values[ref]) if ref in values else None})())
        wire_mode='hold' if mode=='startup-timeout' else mode if mode in ('modern','none') else 'legacy'
        url_path='/native/'+str(index)+'/'+wire_mode
        config=dict(transport='streamable-http',serverName='supervised',url=peer.URL+url_path,headers={},closeTimeoutMs=500,toolCallTimeoutMs=60000,reconnect=dict(enabled=False))
        if mode=='startup-timeout':config['startupTimeoutMs']=100
        if mode in ('credentials','tool-cleanup-error'):
            config.update(expandTemplates=True,headers=dict(Authorization='Bearer ${credential:TOKEN}'))
            if mode=='tool-cleanup-error':values['TOKEN']='synthetic/token'
        if mode=='reconnect-budget':config['reconnect']=dict(enabled=True,initialDelayMs=5,maxDelayMs=10000,maxAttempts=1)
        if mode=='registration-conflict':names.add('mcp__supervised__a')
        cell=McpStatusCell(lambda *args:None);cell.onChange(lambda status:trace.append(normalized(dict(status))))
        connection=SupervisedMcpConnection(ctx,config,resolve_reconnect_policy(config['reconnect']),cell)
        async def wait(predicate):
            async def spin():
                while not predicate():await asyncio.sleep(.005)
            await asyncio.wait_for(spin(),5)
        try:
            ready=await asyncio.wait_for(asyncio.shield(connection.ready),5)
            checkpoints=[]
            def snapshot():return dict(status=normalized(cell.current()),closure=cell.closure(),names=sorted(names),instructions=connection.instructions())
            checkpoints.append(snapshot())
            if mode=='credentials':
                values['TOKEN']='synthetic/token';ctx.emit('credentials/reference-updated','TOKEN')
                await wait(lambda:cell.current()['state']=='connected');checkpoints.append(snapshot())
                before=len(trace);ctx.emit('credentials/reference-updated','UNRELATED');ctx.emit('credentials/reference-updated','TOKEN');await asyncio.sleep(.025)
                assert len(trace)==before
                values['TOKEN']='rotated/token';ctx.emit('credentials/reference-updated','TOKEN')
                await wait(lambda:len(trace)>before and cell.current()['state']=='connected');checkpoints.append(snapshot())
                values.clear();ctx.emit('credentials/reference-updated','TOKEN')
                await wait(lambda:cell.current()['state']=='waiting-credentials');checkpoints.append(snapshot())
            if mode=='reconnect-budget':
                first=connection.current
                await first.wire.transport.close()
                await wait(lambda:connection.current is not None and connection.current is not first and cell.current()['state']=='connected')
                checkpoints.append(snapshot())
                await connection.current.wire.transport.close()
                await wait(lambda:cell.current().get('reason')=='gave-up' and not names);checkpoints.append(snapshot())
            await connection.dispose();checkpoints.append(snapshot())
            wire=[dict(method=item['packet']['method'],authorization=item['authorization']) for item in peer.records() if item['path']==url_path and item['packet']['method']!='notifications/cancelled']
            rows.append(dict(mode=mode,ready={} if not ready else dict(error=describe_error(ready['error'])),trace=trace,checkpoints=checkpoints,wire=wire,logs=logs))
        finally:
            await connection.dispose();await ctx.fiber.dispose()
    for raw in config_cases():
        try:result=dict(data=RESOURCE_CONFIG(raw))
        except Exception as error:result=dict(error=dict(name=getattr(error,'name',type(error).__name__),message=str(error)))
        rows.append(dict(config=raw,result=result))
    return rows


def prepare(output):
    peer.prepare(output)
    path=output/'input.json';path.write_text(json.dumps(dict(url=peer.URL,log=str(peer.LOG),cases=CASES,configs=config_cases())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_mcp_supervision.mts','Actual original startConnection and native production supervisor, real HTTP generation wires, successful/capability-omitted startup, shared startup deadline, missing/unchanged/rotated/removed credentials, reconnect exhaustion, registry conflict and redacted tool cleanup failure. Timestamps normalized; raw packets retained, stable method/auth sequences compared, cancellation notification scheduling excluded.',[Path(__file__).resolve(),ROOT/'dsh/mcp/connection_current.py',ROOT/'dsh/mcp/current.py',ROOT/'dsh/mcp/tools_current.py',ROOT/'dsh/mcp/tools.py'],prepare=prepare)
    finally:peer.stop_peer()
