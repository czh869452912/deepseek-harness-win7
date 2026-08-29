import datetime
import re
import pytest
from dsh.cordis.context import Context
from dsh.cordis.schema import Schema, z, ValidationError
from dsh.cordis.loader import Loader, Entry

def test_schemastery_simplify_pruning():
    schema = Schema.object({
        'name': Schema.string().default('default_name'),
        'port': Schema.number().default(8080),
        'tags': Schema.array(Schema.string()).default(['a', 'b']),
        'nested': Schema.object({
            'enabled': Schema.boolean().default(True),
            'custom': Schema.string().default('foo'),
        }).default({'enabled': True, 'custom': 'foo'}),
    })
    exact_default = {
        'name': 'default_name',
        'port': 8080,
        'tags': ['a', 'b'],
        'nested': {'enabled': True, 'custom': 'foo'},
    }
    assert schema.simplify(exact_default) is None

    partial_override = {
        'name': 'my_app',
        'port': 8080,
        'tags': ['a', 'b'],
        'nested': {'enabled': False, 'custom': 'foo'},
    }
    simplified = schema.simplify(partial_override)
    assert simplified == {
        'name': 'my_app',
        'nested': {'enabled': False},
    }

def test_schemastery_date_and_regexp():
    date_schema = Schema.date()
    dt = date_schema('2026-08-29T12:00:00')
    assert isinstance(dt, (datetime.datetime, datetime.date))
    assert dt.year == 2026

    with pytest.raises(ValidationError):
        date_schema('invalid-date-string')

    re_schema = Schema.regExp('i')
    pattern = re_schema(r'^test.*')
    assert isinstance(pattern, re.Pattern)
    assert pattern.match('TEST_CASE') is not None

def test_schemastery_array_buffer_and_roles():
    buf_schema = Schema.arrayBuffer('base64')
    res = buf_schema('aGVsbG8=')
    assert res == b'hello'

    slider_schema = Schema.percent()
    assert slider_schema.meta.get('role') == 'slider'
    assert slider_schema.meta.get('max') == 1
    assert slider_schema.meta.get('min') == 0

    meta_schema = (
        Schema.string()
        .role('textarea')
        .badges([{'text': 'pro', 'type': 'info'}])
        .collapse(True)
        .loose(True)
    )
    assert meta_schema.meta.get('role') == 'textarea'
    assert meta_schema.meta.get('badges') == [{'text': 'pro', 'type': 'info'}]
    assert meta_schema.meta.get('collapse') is True
    assert meta_schema.meta.get('loose') is True

def test_reflect_trace_and_bind():
    ctx = Context()
    val = {'hello': 'world'}
    traced = ctx.reflect.trace(val)
    assert traced == val

    called_args = []
    def my_callback(a, b):
        called_args.append((a, b))
        return a + b

    bound = ctx.reflect.bind(my_callback)
    res = bound(10, 20)
    assert res == 30
    assert called_args == [(10, 20)]

def test_event_listener_auto_bind():
    ctx = Context()
    received = []
    def on_custom(val):
        received.append(val)

    ctx.on('custom/event', on_custom)
    ctx.emit('custom/event', 'test-payload')
    assert received == ['test-payload']

def test_loader_internal_update_with_schema_simplify():
    ctx = Context()
    loader = Loader(ctx)

    class MockPlugin:
        Config = Schema.object({
            'debug': Schema.boolean().default(False),
            'port': Schema.number().default(3000),
        })

    mock_entry = Entry(loader.root, {
        'id': 'mock-entry-1',
        'name': 'mock-plugin',
        'config': {'debug': False, 'port': 3000},
    })

    class DummyFiber:
        def __init__(self):
            self.entry = mock_entry
            self.runtime = MockPlugin
            self.plugin = MockPlugin
            self.parent = None
            self.ctx = ctx
            self._hooks = {}

    fiber = DummyFiber()
    mock_entry.fiber = fiber

    ctx.emit('internal/update', {'debug': True, 'port': 3000}, caller_ctx=ctx.extend({'fiber': fiber}))
    assert mock_entry.options['config'] == {'debug': True}
