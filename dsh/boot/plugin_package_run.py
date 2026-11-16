"""Captured package runs; callers own the profile write lock and admission.

This process layer does not reconcile packages or certify an installation.
It owns pipes, bounded output, the full log, cancellation and the run record.
"""
import asyncio
import errno
import json
import os
import tempfile

from dsh.cordis import Context
from dsh.core.abort import NEVER_ABORTED
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from dsh.subprocess.types import SubprocessSpawnSpec, SubprocessStdio
from dsh.util.atomic_write import write_file_atomic

DRAIN_AFTER_EXIT_MS = 2000


async def run_package_process(directory, argv, options):
    """Run one admitted service command, joining its owned tree on all exits."""
    record = os.path.join(directory, '.plugin-manager', 'run.json')
    if os.path.lexists(record):raise RuntimeError('a package run record must be admitted before starting another run')
    log_root = os.path.join(directory, '.plugin-manager', 'logs')
    os.makedirs(log_root, mode=0o700, exist_ok=True)
    log_path = os.path.join(tempfile.mkdtemp(prefix='operation-',dir=log_root), 'pnpm.log')
    log = open(os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb')
    ctx = Context();handle = None;readers = [];timer = None;detach = lambda:None
    signal = options.get('signal') or NEVER_ABORTED
    loop = asyncio.get_running_loop();tail = bytearray();truncated = False;settled = False;stalled = False
    callback = options.get('onOutput');record_text = None;tree_stopped = False
    def append(data):
        nonlocal truncated
        tail.extend(data)
        if len(tail)>options['outputBytes']:
            truncated=True
            del tail[:len(tail)-options['outputBytes']]
    def expire():
        nonlocal stalled
        stalled=True
        handle.terminate()
    def arm_idle():
        nonlocal timer
        if settled or options.get('idleTimeoutMs') is None:return
        if timer is not None:timer.cancel()
        timer=loop.call_later(options['idleTimeoutMs']/1000,expire)
    def emit(data,stream):
        log.write(data);log.flush()
        if callback is not None:callback(data.decode('utf-8',errors='replace'),stream)
        append(data)
    async def received(data,stream):
        arm_idle()
        try:emit(data,stream)
        except BaseException:
            handle.terminate()
            raise
    def copy(stream,name):
        while True:
            data=stream.read1(4096)
            if not data:break
            asyncio.run_coroutine_threadsafe(received(data,name),loop).result()
    try:
        await ctx.plugin(AuthorizedLocalSubprocessRuntime if os.name=='nt' else LocalSubprocessRuntime)
        runtime=ctx.get('subprocess')
        cause=None
        try:
            signal.throwIfAborted()
            if os.name=='nt':
                command=await runtime.resolve_executable(argv[0],options.get('env'),signal)
                handle=runtime.spawn(dict(argv=[command]+argv[1:],cwd=directory,graceMs=1000,env=options.get('env'),
                    stdio=dict(stdin='ignore',stdout='pipe',stderr='pipe')))
            else:
                handle=runtime.spawn(SubprocessSpawnSpec(argv,directory,SubprocessStdio('ignore','pipe','pipe'),1000,env=options.get('env')))
        except Exception as error:cause=error
        if handle is not None:
            detach=signal.add_listener('abort',lambda _:handle.terminate())
            readers=[loop.run_in_executor(None,copy,stream,name) for stream,name in [(handle.stdout,'stdout'),(handle.stderr,'stderr')]]
            arm_idle()
            if handle.pid>0:
                record_text=json.dumps(dict(pid=handle.pid,grouped=os.name!='nt'),separators=(',',':'))+'\n'
                await write_file_atomic(record,record_text,mode=0o600)
            try:
                outcome=await asyncio.shield(handle.done)
                exit_code=outcome['exitCode'] if isinstance(outcome,dict) else outcome.exitCode
            except Exception as error:cause=error;exit_code=None
            settled=True
            if timer is not None:timer.cancel()
            if stalled:
                handle.terminate();await handle.wait_for_exit()
            _,pending=await asyncio.wait(readers,timeout=DRAIN_AFTER_EXIT_MS/1000)
            if pending:
                # The Python host keeps descendants within its Job/process
                # group; stop them before cutting inherited output pipes.
                handle.terminate();await handle.wait_for_exit()
                await asyncio.shield(asyncio.gather(*readers))
                emit(b'dsh: pnpm output was cut short after its process exited\n','stderr')
            else:await asyncio.shield(asyncio.gather(*readers))
        else:exit_code=None
        if stalled:emit(('dsh: pnpm printed nothing for '+str(options['idleTimeoutMs'])+'ms and was terminated\n').encode('utf-8'),'stderr')
        code=getattr(cause,'code',None)
        if code is None and isinstance(cause,OSError):code=errno.errorcode.get(cause.errno)
        if code in ('SUBPROCESS_EXECUTABLE_NOT_FOUND','SUBPROCESS_SPAWN_NOT_FOUND'):code='ENOENT'
        exit_code=exit_code if exit_code is not None and not stalled else 127 if code=='ENOENT' else 1
        if (exit_code!=0 or cause is not None) and not tail:
            diagnostic=(getattr(cause,'message',str(cause)) if cause is not None else 'pnpm failed').encode('utf-8')
            log.write(diagnostic);log.flush()
            if callback is not None:callback(diagnostic.decode('utf-8',errors='replace'),'stderr')
            truncated=len(diagnostic)>options['outputBytes'];tail[:]=diagnostic[:options['outputBytes']]
        result=dict(exitCode=exit_code,output=tail.decode('utf-8',errors='replace'),truncated=truncated,logPath=log_path)
        if stalled:result['timedOut']=True
        return result
    finally:
        settled=True
        if timer is not None:timer.cancel()
        detach()
        try:
            if handle is not None:
                handle.terminate()
                try:await asyncio.shield(handle.done)
                except Exception:pass
                await handle.wait_for_exit()
            await ctx.fiber.dispose()
            tree_stopped = True
            if readers:await asyncio.shield(asyncio.gather(*readers))
        finally:
            if handle is not None:
                for stream in (handle.stdout,handle.stderr):
                    if stream is not None:stream.close()
            log.close()
            if record_text is not None and tree_stopped:
                try:
                    with open(record,encoding='utf-8') as stream:current=stream.read()
                    if current==record_text:os.unlink(record)
                except FileNotFoundError:pass
