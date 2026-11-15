"""Session identity from validated Remote wire arguments, before Host lookup."""
from dsh.core.session.json import UNDEFINED
from dsh.typert.stores import field


def resolve_session_resource(value):
    args, parameters = value['args'], value['parameters']
    for parameter in parameters:
        if parameter.get('name') == 'sessionId' or parameter['wire'] == 'sessionId':
            return args.get(parameter['wire'], UNDEFINED)
    for parameter in parameters:
        request = args.get(parameter['wire'], UNDEFINED)
        if not isinstance(request, dict):
            continue
        identity, address = request.get('sessionId', UNDEFINED), request.get('address', UNDEFINED)
        if identity is not UNDEFINED and address is not UNDEFINED:
            raise ValueError('Session resource request must not contain both sessionId and address')
        if identity is not UNDEFINED and identity is not None:
            return identity
        if address is UNDEFINED:
            return UNDEFINED
        if address is None:
            raise TypeError('Cannot read properties of null (reading kind)')
        return field(address, 'sessionId' if field(address, 'kind', UNDEFINED) == 'session' else 'childSessionId', UNDEFINED)
    return UNDEFINED


def register_session_resource(ctx):
    return ctx.get('typert').resources.register('session', dict(resolve=resolve_session_resource))
