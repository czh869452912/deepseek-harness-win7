"""Current MCP cause-chain diagnostics and instance-secret redaction."""
from dsh.cordis.utils import js_to_string


_ABSENT = object()


class CurrentProtocolError(RuntimeError):
    name='ProtocolError'
    def __init__(self,code,message,data=_ABSENT):
        self.code,self.message=code,message
        if data is not _ABSENT:self.data=data
        super().__init__(message)


class McpLocalError(RuntimeError):
    name = 'Error'

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _units(value):
    encoded = value.encode('utf-16-le', 'surrogatepass')
    return ''.join(chr(int.from_bytes(encoded[index:index+2], 'little')) for index in range(0,len(encoded),2))


def redact_secrets(text, secrets):
    value = _units(text)
    for secret in sorted((_units(item) for item in secrets),key=len,reverse=True):
        value = value.replace(secret,'[redacted]')
    return b''.join(ord(char).to_bytes(2,'little') for char in value).decode('utf-16-le','surrogatepass')


def _name(error):
    return getattr(error,'name','TypeError' if isinstance(error,TypeError) else 'Error')


def _error_string(error):
    name, message = _name(error), str(error)
    return message if not name else name if not message else name+': '+message


def _segment(value):
    if not isinstance(value,BaseException):
        return js_to_string(value)
    name, message = _name(value), str(value)
    base = (name if not message else message) if name=='Error' or not message else name+': '+message
    if base and base!='Error':
        return base
    code = getattr(value,'code',None)
    return code if isinstance(code,str) else name


def describe_error(error):
    seen, segments, current = set(), [], error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        segments.append(_error_string(current) if not segments and isinstance(current,BaseException) else _segment(current))
        current = getattr(current,'cause',getattr(current,'__cause__',None)) if isinstance(current,BaseException) else None
    return segments[0]+''.join(', cause: '+segment for segment in segments[1:]) if segments else js_to_string(error)
