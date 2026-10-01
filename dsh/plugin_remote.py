"""Experimental public JSON Schema codec for Python-authored Typert contracts."""
import copy

from dsh.core.json_schema import assert_supported_json_schema, validate_json_schema_value
from dsh.core.session.json import snapshot_json_value


class JsonSchemaCodec:
    def __init__(self, schema):
        assert_supported_json_schema(schema)
        self.schema = copy.deepcopy(schema)

    def parse(self, value):
        errors = validate_json_schema_value(self.schema, value)
        if errors:
            raise ValueError('Remote value violates JSON Schema: ' + '; '.join(errors))
        return snapshot_json_value(value)

    def to_json_schema(self, params=None):
        return copy.deepcopy(self.schema)
