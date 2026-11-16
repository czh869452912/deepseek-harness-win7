"""SDK 2 probe decisions, kept separate from transport and retry ownership."""
import json

from dsh.mcp.current import RESOURCE_SCHEMAS
from dsh.mcp.schemas import parse,SchemaError

_ABSENT=object()


class SdkError(RuntimeError):
    name='SdkError'
    def __init__(self,code,message,data=None,cause=_ABSENT):
        self.code=code;self.message=message;self.data=data
        if cause is not _ABSENT:self.cause=cause
        super().__init__(message)


class SdkHttpError(SdkError):
    name='SdkHttpError'


class UnsupportedProtocolVersionError(SdkError):
    name='ProtocolError'
    def __init__(self,supported,requested,message=None):
        super().__init__(-32022,'Unsupported protocol version: '+requested if message is None else message,
            dict(supported=list(supported),requested=requested))


def _rpc(outcome,context):
    if outcome.get('code')!=-32022:return dict(kind='legacy')
    data=outcome.get('data');supported=data.get('supported') if isinstance(data,dict) else None
    if not isinstance(supported,list) or not supported or any(not isinstance(item,str) for item in supported):return dict(kind='legacy')
    requested=data.get('requested')
    error=UnsupportedProtocolVersionError(supported,requested if isinstance(requested,str) else context['requestedVersion'],outcome.get('message',''))
    modern=[version for version in supported if version>='2026-07-28']
    mutual=next((version for version in context['clientModernVersions'] if version in modern),None)
    if mutual is not None:return dict(kind='corrective',version=mutual,error=error)
    if modern or not context['fallbackAvailable']:return dict(kind='error',error=error)
    return dict(kind='legacy')


def _network(error,context):
    if context['environment']=='browser' and (isinstance(error,TypeError) or getattr(error,'name',None)=='TypeError'):
        return dict(kind='legacy')
    return dict(kind='error',error=SdkError('ERA_NEGOTIATION_FAILED','Version negotiation probe failed: '+str(error),dict(cause=error),cause=error))


def classify_probe_outcome(outcome,context):
    kind=outcome['kind']
    if kind=='result':
        try:result=parse('ModernDiscoverResultSchema',outcome['result'],RESOURCE_SCHEMAS)
        except SchemaError:return dict(kind='legacy')
        supported=result['supportedVersions']
        overlap=next((version for version in context['clientModernVersions'] if version in supported),None)
        if overlap is not None:return dict(kind='modern',version=overlap,discover=result)
        return dict(kind='legacy') if context['fallbackAvailable'] else dict(kind='error',error=UnsupportedProtocolVersionError(supported,context['requestedVersion']))
    if kind=='rpc-error':return _rpc(outcome,context)
    if kind=='http-error':
        status=outcome['status']
        data={key:outcome[origin] for key,origin in [('status','status'),('statusText','statusText'),('text','body')] if origin in outcome}
        if status in (401,403):
            message='the server denied access (HTTP 403)' if status==403 else 'the server requires authorization (HTTP 401)'
            code='CLIENT_HTTP_FORBIDDEN' if status==403 else 'CLIENT_HTTP_AUTHENTICATION'
            return dict(kind='error',error=SdkHttpError(code,'Version negotiation failed: '+message,data))
        if status>=500:return dict(kind='error',error=SdkHttpError('ERA_NEGOTIATION_FAILED','Version negotiation failed: the server answered the probe with HTTP '+str(status),data))
        try:
            body=json.loads(outcome.get('body',''));error=body.get('error') if isinstance(body,dict) else None
        except (ValueError,TypeError):error=None
        if isinstance(error,dict) and type(error.get('code')) in (int,float):
            return _rpc(dict(error,message=error['message'] if isinstance(error.get('message'),str) else ''),context)
        return dict(kind='legacy')
    if kind=='network-error':return _network(outcome['error'],context)
    if kind=='auth-required':return dict(kind='error',error=outcome['error'])
    if kind=='closed':
        return dict(kind='legacy') if context['transportKind']=='stdio' else _network(RuntimeError('Connection closed during the version negotiation probe'),context)
    if kind=='timeout':
        return dict(kind='legacy') if context['transportKind']=='stdio' else dict(kind='error',error=SdkError('REQUEST_TIMEOUT',
            'Version negotiation probe timed out after '+str(outcome['timeoutMs'])+'ms',dict(timeout=outcome['timeoutMs'])))
    raise ValueError('unknown MCP probe outcome: '+kind)
