"""Project Python-native Schema graphs with lazy builders owned by the caller.

Only trusted lazy builders cross back into Python. Validators, transform callbacks
and serialization hooks remain opaque. Graph updates retain identity and preserve
the original sequential visit order across the process boundary.
"""
import asyncio
import datetime
import math
import re

from dsh.boot.config_projection_current import projection_bootstrap
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED, _js_key_to_string
from dsh.core.session.json import UNDEFINED
from dsh.javascript.runtime import JavaScriptRuntimeError


def is_native_config_schema(value):
    return isinstance(value, Schema) and isinstance(value.type, str) and isinstance(value.meta, dict)


class ConfigGraph:
    def __init__(self, root):
        self.root = root
        self.objects = []
        self.indices = {}

    def encode(self, value):
        if value is _UNDEFINED or value is UNDEFINED:
            return dict(atom='undefined')
        if value is None or type(value) in (str, bool):
            return value
        if type(value) in (int, float):
            try:
                number = float(value)
            except OverflowError:
                number = float('-inf') if value < 0 else float('inf')
            if not math.isfinite(number):
                return dict(atom='nan' if math.isnan(number) else '-infinity' if number < 0 else 'infinity')
            return value
        index = self.indices.get(id(value))
        if index is None:
            index = len(self.objects)
            self.indices[id(value)] = index
            self.objects.append(value)  # hold identity until the projection closes
        return dict(ref=index)

    def snapshot(self, extra=UNDEFINED):
        root = self.encode(self.root)
        result = self.encode(extra)
        heap = []
        index = 0
        while index < len(self.objects):
            value = self.objects[index]
            if isinstance(value, Schema):
                fields = [('type', value.type), ('meta', value.meta)]
                for key, attribute in [('inner', 'inner'), ('sKey', 's_key'), ('list', 'list'), ('dict', 'dict')]:
                    item = getattr(value, attribute, None)
                    if item is not None:
                        fields.append((key, item))
                if value.type == 'const':
                    fields.append(('value', value.value if value.value_provided or value.value is not None else UNDEFINED))
                record = dict(kind='schema', entries=[[key, self.encode(item)] for key, item in fields])
                if callable(getattr(value, 'builder', None)):
                    record['builder'] = dict(deferred=True)
            elif type(value) in (list, tuple):
                record = dict(kind='array', items=[self.encode(item) for item in value])
            elif type(value) is dict:
                record = dict(kind='object', entries=[[_js_key_to_string(key), self.encode(item)] for key, item in value.items()])
            elif isinstance(value, (datetime.datetime, datetime.date)):
                record = dict(kind='date', value=value.isoformat())
            elif isinstance(value, re.Pattern):
                flags = ''.join(flag for bit, flag in [(re.I, 'i'), (re.M, 'm'), (re.S, 's')] if value.flags & bit)
                record = dict(kind='regexp', source=value.pattern, flags=flags)
            elif callable(value):
                record = dict(kind='function')
            else:
                record = dict(kind='opaque')
            heap.append(record)
            index += 1
        return dict(heap=heap, roots=[root]), result


async def project_native_config(ctx, root, prefix='config'):
    """Project one live native Config graph; dispose its worker on every exit."""
    if not is_native_config_schema(root):
        raise TypeError('Config projection requires a native Schema graph')
    runtime = ctx.get('jsRuntime')
    if runtime is None:
        raise RuntimeError('Config projection requires the mounted JavaScript runtime')
    graph = ConfigGraph(root)
    worker = None
    builder_error = None

    async def observe(message):
        nonlocal builder_error
        if message.get('type') != 'config-builder':
            raise JavaScriptRuntimeError('Config projector returned an unexpected message')
        index = message.get('index')
        if type(index) is not int or not 0 <= index < len(graph.objects):
            raise JavaScriptRuntimeError('Config projector requested an invalid builder')
        node = graph.objects[index]
        if not isinstance(node, Schema) or not callable(node.builder):
            raise JavaScriptRuntimeError('Config projector requested a non-builder')
        try:
            value = node.builder()
            snapshot, encoded = graph.snapshot(value)
            await worker.send(dict(type='config-builder-result', index=index, graph=snapshot, value=encoded))
        except Exception as error:
            builder_error = error
            await worker.send(dict(type='config-builder-result', index=index, error=str(error)))

    initial, _ = graph.snapshot()
    request = dict(body='return null', name='cordis-native-config-projection', timeoutMs=5000,
                   nativeGraph=initial, prefix=prefix, bootstrap=projection_bootstrap())
    try:
        worker = await runtime.open(request, observe)
        await worker.send(dict(type='go'))
        result = await asyncio.shield(worker.result)
        if type(result) is not dict or type(result.get('ok')) is not bool:
            raise JavaScriptRuntimeError('Config projector returned an invalid result')
        if not result['ok']:
            if builder_error is not None and result.get('error') == str(builder_error):
                raise builder_error
            raise ValueError(result.get('error', 'Config projection failed'))
        return result['value']
    finally:
        if worker is not None:
            await asyncio.shield(worker.dispose())
