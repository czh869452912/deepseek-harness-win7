"""Resource identities read from validated wire arguments before Host lookup."""
from dsh.core.session.json import UNDEFINED
from dsh.typert.stores import field


GLOBAL = (dict(kind='global'),)
_INVALID = object()


def _read(reader, absent):
    try:
        value = reader()
    except Exception:
        return _INVALID
    if value is UNDEFINED:
        return absent
    if not isinstance(value, list):
        return [value]
    return value if value else _INVALID


def _collect(resources, kind, ids):
    if ids is _INVALID:
        return False
    for identity in ids:
        if not isinstance(identity, str) or not identity:
            return False
        resources.append(dict(kind=kind, id=identity))
    return True


def _default_field(descriptor, args, name):
    if any(parameter['wire'] == name for parameter in descriptor['parameters']):
        return args.get(name, UNDEFINED)
    for parameter in descriptor['parameters']:
        value = args.get(parameter['wire'], UNDEFINED)
        if not isinstance(value, dict):
            continue
        return value.get(name, UNDEFINED)
    return UNDEFINED


def call_resources(typert, readers, descriptor, args, signal):
    sources = {}
    positional = [args.get(parameter['wire'], UNDEFINED) for parameter in descriptor['parameters']]
    if 'cancellation' in descriptor:
        positional.append(signal)
    for declaration in typert.resources.entries():
        def default(declaration=declaration):
            try:
                value = declaration['resolve'](dict(args=args, parameters=descriptor['parameters'])) if 'resolve' in declaration else _default_field(descriptor, args, declaration['field'])
            except Exception:
                return _INVALID
            return _INVALID if isinstance(value, list) else [] if value is UNDEFINED else [value]
        sources[declaration['kind']] = default
    lookups = {}
    receiver = descriptor['invocation']
    if receiver['kind'] == 'context':
        kind = field(typert.contexts.getHost(receiver['context']), 'resource', UNDEFINED)
        if kind is not UNDEFINED:
            lookups[kind] = [args.get(receiver['wire'], UNDEFINED)]
    for parameter in descriptor['parameters']:
        if 'lookup' not in parameter:
            continue
        kind = field(typert.lookups.get(parameter['lookup']), 'resource', UNDEFINED)
        identity = args.get(parameter['wire'], UNDEFINED)
        if kind is not UNDEFINED and identity is not UNDEFINED:
            lookups.setdefault(kind, []).append(identity)
    for kind, ids in lookups.items():
        sources[kind] = lambda ids=ids: ids
    for kind, reader in (readers or {}).items():
        sources[kind] = lambda reader=reader: _read(lambda: reader(*positional), [])
    resources = []
    for kind, source in sources.items():
        if not _collect(resources, kind, source()):
            return None
    return resources if resources else [dict(value) for value in GLOBAL]


def event_resources(readers, args):
    if not readers:
        return [dict(value) for value in GLOBAL]
    resources = []
    for kind, reader in readers.items():
        if not _collect(resources, kind, _read(lambda: reader(*args), _INVALID)):
            return None
    return resources


callResources = call_resources
eventResources = event_resources
