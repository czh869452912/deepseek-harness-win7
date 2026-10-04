import json


def parse_json(serialized):
    def reject_constant(value):
        raise ValueError('Invalid JSON numeric constant: ' + value)
    return json.loads(serialized, parse_int=float, parse_constant=reject_constant)
