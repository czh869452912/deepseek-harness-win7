from dsh.llm.error import HarnessError

JOB_ERROR_CODES=('JOB_BACKGROUND_DISABLED','JOB_CONTROLLER_UNAVAILABLE','JOB_NOT_FOUND',
    'JOB_FOREIGN_SESSION','JOB_OWNER_NOT_LIVE','JOB_OWNER_REGISTRY_UNAVAILABLE','JOB_LIMIT_REACHED')


class JobError(HarnessError):
    def __init__(self,message,code,options=None):super().__init__(message,code,options)
