"""Stable business failures for the subagent browser control boundary."""
from dsh.typert.remote import TypertRemoteFailure
from dsh.context.time_context.request_zone import browser_time_zone


def reject(code, message, details=None):
    raise TypertRemoteFailure(dict(code=code, message=message, details=details or {}))


def validate(request, child=False):
    issues = []
    for key in ('parentSessionId', 'childSessionId') if child else ('parentSessionId',):
        if not isinstance(request.get(key), str) or not request[key]:
            issues.append(dict(path=[key], message='must be a non-empty string'))
    if child and request.get('mode') != 'continuable':
        issues.append(dict(path=['mode'], message='must be continuable'))
    if issues:
        reject('bad-request', 'invalid subagent control payload', dict(issues=issues))


async def catalog(service, parent_id, signal):
    validate(dict(parentSessionId=parent_id))
    try:
        rows = await service.listChildren(parent_id, signal)
        agents = service.ctx.get('agents')
        for row in rows:
            if row['kind'] == 'child':
                agent = agents.get(row['id']) if agents is not None else None
                row['activity'] = 'running' if agent is not None and agent.status == 'running' else 'inactive'
        return dict(entries=rows, parentAvailable=agents is not None and agents.get(parent_id) is not None)
    except Exception as error:
        if signal.aborted or getattr(error, 'code', None) == 'CANCELLED':
            reject('cancelled', 'subagent catalog read was cancelled')
        if getattr(error, 'code', None) == 'SUBAGENT_CONTROL_PROJECTIONS_UNAVAILABLE':
            reject('subagent-projections-unavailable', 'subagent catalog requires sessionProjections')
        reject('internal', 'subagent catalog read failed')


async def prompt(service, request, signal):
    validate(request, True)
    source = dict(kind='user', rpcId=request['requestId'])
    if 'clientTimeZone' in request:
        try:
            source['clientTimeZone'] = browser_time_zone(dict(source=dict(source, clientTimeZone=request['clientTimeZone'])))
            if source['clientTimeZone'] is None:
                raise ValueError('missing zone')
        except (TypeError, ValueError):
            reject('invalid-time-zone', 'clientTimeZone must be UTC or a valid IANA Area/Location name', dict(value=request['clientTimeZone']))
    agents = service.ctx.get('agents')
    parent = agents.get(request['parentSessionId']) if agents is not None else None
    if parent is None:
        reject('subagent-parent-unavailable', 'parent session is not live', dict(parentSessionId=request['parentSessionId']))
    try:
        identity = await service.followup(parent, request['childSessionId'], list(request['content']), dict(source=source, signal=signal))
        return dict(messageId=identity)
    except Exception as error:
        if signal.aborted or getattr(error, 'code', None) == 'CANCELLED':
            reject('cancelled', 'subagent prompt was cancelled')
        code = {'NOT_RESUMABLE': 'subagent-not-resumable', 'UNAUTHORIZED': 'subagent-unauthorized',
                'DRAINING': 'subagent-delivery-unavailable', 'ACTIVATION_CLOSING': 'subagent-delivery-unavailable',
                'CONTINUATION_UNAVAILABLE': 'subagent-delivery-unavailable', 'PERSISTENCE_UNAVAILABLE': 'subagent-delivery-unavailable'}.get(getattr(error, 'code', None))
        if code:
            reject(code, 'subagent prompt was not admitted', dict(childSessionId=request['childSessionId']))
        reject('internal', 'subagent prompt failed')


def interrupt(service, child_id, parent_id, mode):
    validate(dict(childSessionId=child_id, parentSessionId=parent_id, mode=mode), True)
    try:
        service.interrupt(child_id, dict(kind='user', parentSessionId=parent_id))
    except Exception as error:
        if getattr(error, 'code', None) == 'UNAUTHORIZED':
            reject('subagent-unauthorized', 'subagent does not belong to this parent', dict(childSessionId=child_id))
        reject('internal', 'subagent interrupt failed')
    return dict(accepted=True)
