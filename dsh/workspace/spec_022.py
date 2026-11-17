"""Current Workspace durable pin/default identity fields at version two."""
from dsh.storage.domain_spec import DomainGlobalSpec, SchemaValidator, define_domain, domain_table


def strings(value):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('expected string array')
    return list(value)


def record(value):
    if not isinstance(value, dict):raise ValueError('expected workspace record')
    result = {}
    for key in ('path', 'title', 'createdAt', 'updatedAt'):
        if not isinstance(value.get(key), str):raise ValueError('expected workspace '+key)
        result[key] = value[key]
    result['sessionIds'] = strings(value.get('sessionIds'))
    return result


def state(value):
    if not isinstance(value, dict) or type(value.get('initialized')) is not bool:
        raise ValueError('expected workspace initialized flag')
    result = dict(initialized=value['initialized'],workspaceIds=strings(value.get('workspaceIds')),
        archivedSessionIds=strings(value.get('archivedSessionIds',[])),pinnedSessionIds=strings(value.get('pinnedSessionIds',[])))
    if 'defaultWorkspaceId' in value:
        if not isinstance(value['defaultWorkspaceId'],str):raise ValueError('expected default workspace id')
        result['defaultWorkspaceId']=value['defaultWorkspaceId']
    if 'pendingMutation' in value:
        pending=value['pendingMutation']
        if not isinstance(pending,dict) or pending.get('operation') not in ('create','delete') or not isinstance(pending.get('workspaceId'),str):
            raise ValueError('expected pending workspace mutation')
        result['pendingMutation']=dict(operation=pending['operation'],workspaceId=pending['workspaceId'])
    return result


workspace_domain_spec = define_domain(name='workspace',version=2,
    global_spec=DomainGlobalSpec(SchemaValidator(state),dict(initialized=False,workspaceIds=[],archivedSessionIds=[],pinnedSessionIds=[])),
    tables=dict(workspaces=domain_table(SchemaValidator(record))))
