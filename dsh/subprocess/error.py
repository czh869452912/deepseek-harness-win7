"""Machine-routable canonical subprocess failures."""
from dsh.llm.error import HarnessError
from dsh.cordis.json_text import stringify_json
import errno

SUBPROCESS_ERROR_CODES=('SUBPROCESS_INVALID_ARGV','SUBPROCESS_EXECUTABLE_NOT_FOUND',
    'SUBPROCESS_SPAWN_NOT_FOUND','SUBPROCESS_SPAWN_FAILED','SUBPROCESS_RUNNER_FAILED',
    'SUBPROCESS_RUNNER_IPC_FAILED','SUBPROCESS_PTY_UNAVAILABLE')


class SubprocessError(HarnessError):
    name='SubprocessError'
    def __init__(self,message,code,options=None):
        super().__init__(message,code,options)


class SubprocessExecutableNotFoundError(SubprocessError):
    name='SubprocessExecutableNotFoundError'

    def __init__(self,message,options=None):
        super().__init__(message,'SUBPROCESS_EXECUTABLE_NOT_FOUND',options)


def subprocess_spawn_failure(error,program):
    """Classify platform launch failures while retaining the original cause."""
    if not isinstance(error,Exception) or isinstance(error,HarnessError):
        return error
    code=getattr(error,'code',None)
    # Python exposes errno as an integer; Node exposes its symbolic spelling.
    if code is None and isinstance(error,OSError):
        code=errno.errorcode.get(error.errno)
        if code is None and getattr(error,'winerror',None) in (2,3):code='ENOENT'
    if not isinstance(code,str):
        return error
    detail=getattr(error,'message',str(error))
    if code=='ENOENT':
        return SubprocessError('cannot start %s: the program or the working directory does not exist (%s)' %
            (stringify_json(program),detail),'SUBPROCESS_SPAWN_NOT_FOUND',dict(cause=error))
    return SubprocessError('cannot start %s: %s' % (stringify_json(program),detail),
        'SUBPROCESS_SPAWN_FAILED',dict(cause=error))


subprocessSpawnFailure=subprocess_spawn_failure
