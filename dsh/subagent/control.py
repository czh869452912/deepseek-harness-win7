"""Candidate target-only browser controls; Gateway resource binding is separate."""
from dsh.attachment.error import AttachmentError
from dsh.core.session.json import UNDEFINED
from dsh.subagent.errors import SubagentError
from dsh.typert.principal import principal_of
from dsh.typert.remote import RemoteError
from dsh.util_time import canonical_client_time_zone


def received(value):
    return ('undefined' if value is UNDEFINED else 'null' if value is None else 'boolean' if type(value) is bool
        else 'string' if isinstance(value,str) else 'number' if type(value) in (int,float) else 'array' if isinstance(value,list) else 'object')


def validate_control_request(method, payload):
    if not isinstance(payload,dict):
        issues=[dict(expected='object',code='invalid_type',path=[],message='Invalid input: expected object, received '+received(payload))]
    else:
        issues=[]
        value=payload.get('childSessionId',UNDEFINED)
        if not isinstance(value,str):
            issues.append(dict(expected='string',code='invalid_type',path=['childSessionId'],message='Invalid input: expected string, received '+received(value)))
        elif not value:
            issues.append(dict(origin='string',code='too_small',minimum=1,inclusive=True,path=['childSessionId'],message='Too small: expected string to have >=1 characters'))
        if method=='subagent.prompt' and payload.get('delivery',UNDEFINED) not in ('queue','steer'):
            issues.append(dict(code='invalid_value',values=['queue','steer'],path=['delivery'],message='Invalid option: expected one of "queue"|"steer"'))
    if issues:raise RemoteError('gateway/bad-request','invalid payload for '+method,dict(issues=issues))


def reject_prompt(error, child, signal):
    if signal.aborted or isinstance(error,SubagentError) and error.code=='CANCELLED':
        raise RemoteError('gateway/cancelled','subagent prompt was cancelled',{},error)
    if isinstance(error,AttachmentError) or isinstance(error,SubagentError) and error.code=='MODEL_DOES_NOT_SUPPORT_IMAGES':
        raise RemoteError('subagent/attachment-invalid',error.message,dict(reason=error.code),error)
    if isinstance(error,SubagentError):
        suffix,message={
            'NOT_RESUMABLE':('not-resumable','subagent cannot be resumed'),
            'UNAUTHORIZED':('unauthorized','subagent membership in the active tree could not be verified'),
            **{key:('delivery-unavailable','subagent follow-up is temporarily unavailable') for key in
                ('DRAINING','ACTIVATION_CLOSING','ACTIVATION_LIMIT_REACHED','CONTINUATION_UNAVAILABLE','PERSISTENCE_UNAVAILABLE')},
        }.get(error.code,(None,None))
        if suffix is not None:raise RemoteError('subagent/'+suffix,message,dict(childSessionId=child),error)
    raise RemoteError('gateway/internal','subagent prompt failed',{},error)


async def prompt(service,request,signal):
    validate_control_request('subagent.prompt',request)
    zone=canonical_client_time_zone(request['clientTimeZone']) if 'clientTimeZone' in request else None
    if 'clientTimeZone' in request and zone is None:
        raise RemoteError('subagent/invalid-time-zone','clientTimeZone must be UTC or a valid IANA Area/Location name',dict(value=request['clientTimeZone']))
    source=dict(kind='user',rpcId=request['requestId'])
    if zone is not None:source['clientTimeZone']=zone
    principal=principal_of(getattr(service.ctx,'invocation',None))
    if principal is not UNDEFINED:source['principal']=principal
    try:
        parts=request['content']
        if all(part['type']=='text' for part in parts):content=[dict(type='text',text=part['text']) for part in parts]
        else:
            attachments=service.ctx.get('attachments')
            if attachments is None:raise RuntimeError('subagent image prompt requires an attachment store')
            content=await attachments.admitPromptContent(parts)
        identity=await service.require_manager().deliver_prompt(request['childSessionId'],content,dict(source=source,signal=signal,delivery=request['delivery']))
        return dict(messageId=identity)
    except Exception as error:reject_prompt(error,request['childSessionId'],signal)


def interrupt_by_user(service,child):
    validate_control_request('subagent.interrupt',dict(childSessionId=child))
    try:service.interrupt(child,dict(kind='user'))
    except Exception as error:raise RemoteError('gateway/internal','subagent interrupt failed',{},error)
    return dict(accepted=True)
