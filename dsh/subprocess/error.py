"""Machine-routable canonical subprocess failures."""
from dsh.llm.error import HarnessError

SUBPROCESS_ERROR_CODES=('SUBPROCESS_INVALID_ARGV','SUBPROCESS_EXECUTABLE_NOT_FOUND',
    'SUBPROCESS_SPAWN_NOT_FOUND','SUBPROCESS_SPAWN_FAILED','SUBPROCESS_RUNNER_FAILED',
    'SUBPROCESS_RUNNER_IPC_FAILED','SUBPROCESS_PTY_UNAVAILABLE')


class SubprocessError(HarnessError):
    name='SubprocessError'
    def __init__(self,message,code,options=None):
        super().__init__(message,code,options)
