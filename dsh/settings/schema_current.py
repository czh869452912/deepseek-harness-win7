"""Editable Config forms derived from volatile schema ancestors."""
from dsh.cordis.schema import Schema
from dsh.cordis.volatile import is_volatile
from dsh.settings.redact import redact_secrets


def plain_config(value):
    if is_volatile(value):
        return plain_config(value.get())
    if isinstance(value, list):
        return [plain_config(item) for item in value]
    if isinstance(value, dict):
        return {key: plain_config(item) for key, item in value.items()}
    return value


def plain_schema(schema):
    result = Schema(schema.toJSON())
    def walk(node):
        node.meta.pop('volatile', None)
        if node.meta.get('role') == 'secret':
            node.meta.pop('default', None)
            node.meta.pop('required', None)
        elif 'default' in node.meta:
            node.meta['default'] = redact_secrets(node, node.meta['default']).value
        for child in (node.dict or {}).values():
            walk(child)
        if node.inner is not None:
            walk(node.inner)
        for child in node.list or []:
            walk(child)
    walk(result)
    return result


def volatile_form(schema):
    if schema.meta.get('volatile'):
        return plain_schema(schema)
    if schema.type == 'object':
        fields = {}
        for key, child in (schema.dict or {}).items():
            form = volatile_form(child)
            if form is not None:
                fields[key] = form
        return Schema.object(fields) if fields else None
    return None


def project_form(schema, value):
    if schema.type == 'object' and isinstance(value, dict) and not (
            len(value) == 1 and isinstance(value.get('__jsExpr'), str)):
        return {key: project_form(child, value[key]) for key, child in (schema.dict or {}).items() if key in value}
    return value


def is_volatile_path(schema, path):
    if schema.meta.get('volatile'):
        return True
    if not path:
        return False
    child = (schema.dict or {}).get(path[0])
    return child is not None and is_volatile_path(child, path[1:])
