"""Independent native construction of shared diagnostic graph recipes."""
from dsh.cordis.utils import _UNDEFINED
from dsh.llm.error import AggregateError, HarnessError


class DiagnosticError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.name = 'Error'


def build(spec):
    nodes = {}
    for identity, node in spec['nodes'].items():
        kind = node['type']
        properties = {}
        for field in node.get('hostile', []):
            def getter(self):
                raise RuntimeError('hostile getter')
            def setter(self, value, key=field):
                self.__dict__[key] = value
            properties[field] = property(getter, setter)
        if kind in ('error', 'aggregate', 'harness'):
            base = dict(error=DiagnosticError, aggregate=AggregateError, harness=HarnessError)[kind]
            cls = type('FixtureError', (base,), properties) if properties else base
            if kind == 'aggregate':
                value = cls([], node['message'])
            elif kind == 'harness':
                value = cls(node['message'], node['code'])
            else:
                value = cls(node['message'])
            if 'name' in node:
                value.name = node['name']
        elif kind == 'value':
            value = _UNDEFINED if node.get('special') == 'undefined' else node['value']
        else:
            if 'inheritedMessage' in node:
                properties['message'] = node['inheritedMessage']
            value = type('Plain', (), properties)()
            if 'message' in node:
                value.__dict__['message'] = node['message']
            if node.get('coercion') == 'throw':
                def coerce():
                    raise RuntimeError('hostile coercion')
                value.toString = coerce
            elif node.get('coercion') == 'primitive':
                value.toString = lambda result=node['value']: result
            elif node.get('coercion') == 'object':
                value.toString = lambda: {}
                if 'valueOf' in node:
                    value.valueOf = lambda result=node['valueOf']: result
        nodes[identity] = value

    def resolve(value):
        return nodes[value['ref']] if isinstance(value, dict) and 'ref' in value else value

    for identity, node in spec['nodes'].items():
        value = nodes[identity]
        if 'cause' in node:
            value.cause = resolve(node['cause'])
        if node['type'] == 'aggregate':
            value.errors = [resolve(item) for item in node['errors']]
    return nodes[spec['root']]
