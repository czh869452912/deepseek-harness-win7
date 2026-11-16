"""Pair stable status cells, contained observers, diagnostics and deadlines."""
import asyncio
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def inputs():
    return dict(diagnostics=[dict(value=None),dict(value=False),dict(value={'fixture':1}),dict(error=True,message='outer',cause=dict(error=True,name='TypeError',message='inner')),
        dict(error=True,message='',cause=dict(error=True,message='',code='ECONNREFUSED')),dict(error=True,name='',message='only message'),
        dict(error=True,name='SdkError',message='outer',cause=dict(value='raw cause')),dict(error=True,message='cycle',cycle=True)],
        redactions=[dict(text='abcabcdabc',secrets=['abc','abcd']),dict(text='plain',secrets=[]),dict(text='\U0001f600x',secrets=['\ud83d']),dict(text='\U0001f600abcd\U0001f600',secrets=['\U0001f600','abcd']),dict(text='ab',secrets=[''])])


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.errors import ThrownValueError
    from dsh.mcp.status_current import McpStatusCell,register_status_cell,connection_status_in
    from dsh.mcp.diagnostic_current import describe_error,redact_secrets
    from dsh.mcp.deadline_current import with_deadline
    trace=[];warns=[];cell=McpStatusCell(lambda message,error:warns.append(['old',message,describe_error(error)]))
    held=asyncio.get_running_loop().create_future();remove_other=None
    def late(value):trace.append(['late',value['state']])
    def first(value):trace.append(['first',value['state']]);remove_other();cell.onChange(late)
    cell.onChange(first)
    remove_other=cell.onChange(lambda value:trace.append(['other',value['state']]))
    def sync(_):trace.append('sync');raise RuntimeError('sync failure')
    async def asynchronous(_):trace.append('async-start');await held;raise TypeError('async failure')
    cell.onChange(sync);cell.onChange(asynchronous)
    value=dict(state='connected',toolCount=2,connectedAt=123);cell.update(value);before=list(trace);identity=cell.current() is value
    cell.setWarningSink(lambda message,error:warns.append(['new',message,describe_error(error)]));held.set_result(None)
    for _ in range(6):await asyncio.sleep(0)
    cell.opened();opened=cell.closure();closure=dict(closeConfirmed=True,cleanupError='observed');cell.recordClosure(closure)
    cell.update(dict(state='failed',reason='gave-up'))
    for _ in range(6):await asyncio.sleep(0)
    cell.detach();cell.update(dict(state='closed',result=closure))
    ctx=Context();unknown=connection_status_in(ctx.fiber) is None
    registered=register_status_cell(ctx.fiber,lambda *_:None);again=register_status_cell(ctx.fiber,lambda *_:None)
    lookup=connection_status_in(ctx.fiber) is registered;await ctx.fiber.dispose()
    lifetime=dict(unknown=unknown,same=registered is again,lookup=lookup,readable=connection_status_in(ctx.fiber) is registered)
    def build(row):
        if not row or not row.get('error'):return row.get('value') if row else None
        error=TypeError(row['message']) if row.get('name')=='TypeError' else RuntimeError(row['message'])
        if 'name' in row:error.name=row['name']
        if 'code' in row:error.code=row['code']
        if 'cause' in row:error.cause=build(row['cause'])
        if row.get('cycle'):error.cause=error
        return error
    data=inputs();diagnostics=[describe_error(build(spec)) for spec in data['diagnostics']]
    pending=asyncio.get_running_loop().create_future()
    try:await with_deadline(pending,1,'deadline exceeded')
    except Exception as error:deadline=describe_error(error)
    pending.set_result(7);late_value=await pending
    async def reject():raise ThrownValueError({'fixture':1})
    try:await with_deadline(reject(),100,'unused')
    except Exception as error:wrapped=describe_error(error)
    return dict(before=before,trace=trace,warns=warns,identity=identity,opened=opened,closureIdentity=cell.closure() is closure,current=cell.current(),lifetime=lifetime,diagnostics=diagnostics,redacted=[redact_secrets(row['text'],row['secrets']) for row in data['redactions']],deadline=deadline,lateValue=late_value,wrapped=wrapped)


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(inputs()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_status.mts','Original status-cell snapshot observer ordering/containment, warning sink replacement, closure identity and actual Fiber lookup lifetime; diagnostic cause cycles/UTF-16 redaction; noncancelling deadlines. Supervisor publication/reload fences are separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/status_current.py',ROOT/'dsh/mcp/diagnostic_current.py',ROOT/'dsh/mcp/deadline_current.py'],prepare=prepare)
