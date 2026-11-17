"""Live Loader Config directory and input-schema inspection for current Cordis."""
import json
import math

from dsh.boot.config_graph_current import is_native_config_schema, project_native_config
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.json_text import stringify_json
from dsh.core.cleanup import CleanupPromise
from dsh.core.session.json import UNDEFINED


def _field(value, key, default=UNDEFINED):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _live(entry):
    options = entry.options
    listed = dict(id=entry.id, patchId=options['id'], name=options['name'])
    # Native Loader stores absent optional links as None, rather than undefined.
    if _field(entry, 'subgroup', None) is not None or _field(entry, 'subtree', None) is not None:
        return dict(listed, status='tree'), None
    fiber = _field(entry, 'fiber', None)
    if fiber is None or _field(fiber, 'uid', None) is None or entry.disabled:
        return dict(listed, status='inactive'), None
    config = _field(_field(fiber, 'runtime', None), 'Config', None)
    if config is None or config is UNDEFINED:
        return dict(listed, status='absent'), None
    if not is_native_config_schema(config):
        return dict(listed, status='unsupported'), None
    return dict(listed, status='schema'), config


def _query(input):
    fields = input if type(input) is dict else {}
    offset, limit = fields.get('offset'), fields.get('limit')
    if offset is None or offset is UNDEFINED:
        offset = 0
    if limit is None or limit is UNDEFINED:
        limit = 25
    def integer(value):
        if type(value) not in (int, float):
            return False
        try:
            number = float(value)
        except OverflowError:
            return False
        return math.isfinite(number) and number.is_integer()
    if not integer(offset) or offset < 0:
        raise ValueError('offset must be a non-negative integer')
    if not integer(limit) or not 1 <= limit <= 100:
        raise ValueError('limit must be an integer from 1 to 100')
    def text(key):
        value = fields.get(key, UNDEFINED)
        if value is not UNDEFINED and (type(value) is not str or not value):
            raise ValueError(key + ' must be a non-empty string')
        return value
    return text('entry'), text('name'), int(offset), int(limit)


def _expression_schema():
    return dict(type='object', properties=dict(__jsExpr=dict(type='string')), required=['__jsExpr'],
        description='Inert representation of a YAML !!js scalar from the Cordis entry-list parser. Its result is evaluated and validated only at runtime. Extra marker-object fields are ignored by interpolation.')


def query_live_config(ctx, input=UNDEFINED):
    """Return a Promise analogue with the original eager directory-read prefix."""
    async def query():
        loader = ctx.get('loader')
        if loader is None or loader is UNDEFINED:
            raise RuntimeError('Config inspection requires the Loader that mounted this profile; this Host was composed without one')
        entry_id, name, offset, limit = _query(input)
        entries = [_live(entry) for entry in loader.entries()]
        if entry_id is UNDEFINED:
            matching = [listed for listed, _ in entries if name is UNDEFINED or listed['name'] == name]
            page = matching[offset:offset + limit]
            end = offset + len(page)
            return dict(entries=page, total=len(matching), nextOffset=end if end < len(matching) else None)
        selected = next(((listed, native) for listed, native in entries if listed['id'] == entry_id), None)
        if selected is None:
            raise ValueError('unknown entry id ' + stringify_json(entry_id))
        listed, native = selected
        owner = loader.resolve(entry_id)
        base = _field(owner.parent.tree.ctx, 'baseUrl', None)
        packages = ctx.get('pluginPackages')
        if base is not None and base is not UNDEFINED and packages is not None and packages is not UNDEFINED:
            package = packages.packageOf(owner.options['name'], base)
            directory = _field(package, 'dir')
            if directory is not UNDEFINED:
                listed['packageDir'] = directory
        if native is None:
            return listed
        projected = await project_native_config(ctx, native, 'config')
        definitions = dict(projected['definitions'], loaderExpression=_expression_schema())
        schema = dict({'$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': definitions}, **projected['schema'])
        return json.loads(stringify_json(dict(listed, acceptsMissing=projected['acceptsMissing'],
            limitations=projected['limitations'], schema=schema)))
    return CleanupPromise(start_coroutine(query()))
