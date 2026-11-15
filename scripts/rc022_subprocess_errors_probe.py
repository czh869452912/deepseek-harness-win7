"""Canonical subprocess error identity, classification and original causes."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.llm.error import HarnessError
    from dsh.subprocess.error import SubprocessError,SubprocessExecutableNotFoundError,subprocess_spawn_failure,SUBPROCESS_ERROR_CODES
    rows=[]
    for code in ['ENOENT','EACCES','EIO','',1,None]:
        error=RuntimeError('platform failure');error.code=code
        value=subprocess_spawn_failure(error,'C:\\工具\\shell.exe')
        rows.append(dict(name='classify',input=code,same=value is error,harness=isinstance(value,HarnessError),code=getattr(value,'code',None),message=getattr(value,'message',str(value)),cause=getattr(value,'cause',None) is error))
    for value in ['raw',None,dict(code='ENOENT'),HarnessError('unavailable','SANDBOX_UNAVAILABLE'),SubprocessError('owned','SUBPROCESS_RUNNER_FAILED')]:
        result=subprocess_spawn_failure(value,'shell');rows.append(dict(name='preserve',same=result is value))
    cause=RuntimeError('cause');error=SubprocessExecutableNotFoundError('missing',dict(cause=cause))
    rows.append(dict(name='lookup',harness=isinstance(error,HarnessError),subprocess=isinstance(error,SubprocessError),code=error.code,message=error.message,errorName=error.name,cause=error.cause is cause,codes=list(SUBPROCESS_ERROR_CODES)))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_subprocess_errors.mts','Actual canonical subprocess error classes and spawn failure classifier: stable code list, lookup subclass, platform errno strings, exact preservation of HarnessError/non-errno/non-Error values and cause identity. Native OSError numeric errno adaptation separately tested.',[Path(__file__).resolve(),ROOT/'dsh/subprocess/error.py',ROOT/'dsh/subprocess/local_authorized.py'])
