"""Named input and direct invocation capabilities of generated Remote methods."""
from dsh.typert.artifact import UNDEFINED


def field(value, name, default=UNDEFINED):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def optional(parameter):
    return parameter['source'] == 'json' and parameter.get('acceptsUndefined') is True


class NamedInputSchema:
    def __init__(self, parameters, strict):
        self.fields = [(parameter['wire'], optional(parameter),
                        parameter['strictCodec' if strict else 'codec']['create']()) for parameter in parameters]

    def parse(self, value):
        if not isinstance(value, dict) or set(value)-{row[0] for row in self.fields}:
            raise ValueError('typert: named input must be a strict object')
        result = {}
        for name, may_omit, schema in self.fields:
            item = value.get(name, UNDEFINED)
            if item is UNDEFINED:
                if not may_omit:raise ValueError('typert: required named input '+name+' is undefined')
                if name in value:result[name] = UNDEFINED
                continue
            parsed = schema.parse(item)
            if parsed is UNDEFINED and not may_omit:raise ValueError('typert: required named input '+name+' is undefined')
            result[name] = parsed
        return result


class NamedInput:
    def __init__(self, parameters, strict):
        self.parameters, self.strict = parameters, strict
        self._schema, self._projection = None, None

    def create(self):
        if self._schema is None:self._schema = NamedInputSchema(self.parameters, self.strict)
        return self._schema

    def _project(self):
        if self._projection is not None:return self._projection
        codec_key = 'strictCodec' if self.strict else 'codec'
        for parameter in self.parameters:
            codec = parameter[codec_key]
            if codec.get('jsonSchema', UNDEFINED) is UNDEFINED:
                error=codec.get('jsonSchemaError', UNDEFINED)
                if error is UNDEFINED or error is None:error='No JSON Schema for parameter '+parameter['wire']
                self._projection = dict(jsonSchemaError=error)
                return self._projection
        properties = {}
        for parameter in self.parameters:
            properties[parameter['wire']] = dict(parameter[codec_key]['jsonSchema'])
            if parameter.get('description', UNDEFINED) is not UNDEFINED:properties[parameter['wire']]['description'] = parameter['description']
        self._projection = dict(jsonSchema=dict(type='object', properties=properties,
            required=[parameter['wire'] for parameter in self.parameters if not optional(parameter)], additionalProperties=False))
        return self._projection

    @property
    def jsonSchema(self):return self._project().get('jsonSchema', UNDEFINED)

    @property
    def jsonSchemaError(self):return self._project().get('jsonSchemaError', UNDEFINED)


def attach_direct_method(row):
    """Keep helper calls on the original descriptor and the Remote namespace."""
    inputs = {}
    def input_schema(options=None):
        strict = field(options, 'strict', False) is True
        if strict not in inputs:inputs[strict] = NamedInput(row['parameters'], strict)
        return inputs[strict]
    def invoke(remote, named, signal=UNDEFINED):
        if named is None or named is UNDEFINED:raise TypeError('typert: named input is null or undefined')
        values = [field(named, parameter['wire']) for parameter in row['parameters']]
        if row.get('cancellation', UNDEFINED) is not UNDEFINED:values.append(signal)
        receiver = field(remote, row['namespace'])
        method = field(receiver, row['method'])
        if not callable(method):raise TypeError('typert: Remote namespace method is not callable')
        return method(*values)
    row.update(input=input_schema, invoke=invoke)
    return row


def is_typert_remote_method(row):
    return (field(field(row, 'invocation'), 'kind') == 'direct'
            and field(field(row, 'result'), 'mode') == 'strict'
            and callable(field(row, 'input')) and callable(field(row, 'invoke')))


isTypertRemoteMethod = is_typert_remote_method
