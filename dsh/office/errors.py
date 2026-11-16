class OfficeKitError(RuntimeError):
    name='OfficeKitError'

    def __init__(self,code,message,*,cause=None):
        super().__init__(message);self.code=code;self.message=message
        if cause is not None:self.cause=cause
