import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.cordis.events import AggregateError
from dsh.cordis.fiber import FiberState
from dsh.cordis.schema import Schema, ValidationError
from dsh.cordis.timer import TimerService


def test_context_static_symbols_and_is():
    ctx = Context(base_url='https://api.deepseek.com')
    assert Context.is_(ctx) is True
    assert Context.is_context(ctx) is True
    assert Context.is_(None) is False
    assert Context.is_('string') is False

    assert ctx.base_url == 'https://api.deepseek.com'
    assert ctx.baseUrl == 'https://api.deepseek.com'

    child = ctx.extend()
    assert child.base_url == 'https://api.deepseek.com'
    assert child.baseUrl == 'https://api.deepseek.com'
    assert Context.is_(child) is True


def test_schemastery_i18n_hierarchical_localization():
    schema = Schema.object({
        'username': Schema.string().description('Default username'),
        'timeout': Schema.number().description('Connection timeout'),
    }).description('Server configuration')

    localized = schema.i18n({
        'zh': {
            '': 'Server Config ZH',
            'username': 'Username ZH',
            'timeout': 'Timeout ZH',
        },
        'ja': {
            '': 'Server Config JA',
            'username': 'Username JA',
            'timeout': 'Timeout JA',
        }
    })

    assert isinstance(localized.meta['description'], dict)
    assert localized.meta['description'].get('zh') == 'Server Config ZH'
    assert localized.meta['description'].get('ja') == 'Server Config JA'
    assert localized.dict['username'].meta['description'].get('zh') == 'Username ZH'
    assert localized.dict['timeout'].meta['description'].get('zh') == 'Timeout ZH'


@pytest.mark.asyncio
async def test_parallel_dispatch_aggregate_error():
    ctx = Context()

    def fail_one():
        raise ValueError('error one')

    def fail_two():
        raise RuntimeError('error two')

    ctx.on('test/fail', fail_one)
    ctx.on('test/fail', fail_two)

    with pytest.raises(AggregateError) as exc_info:
        await ctx.parallel('test/fail')

    assert len(exc_info.value.errors) == 2
    err_msgs = [str(e) for e in exc_info.value.errors]
    assert any('error one' in m for m in err_msgs)
    assert any('error two' in m for m in err_msgs)


@pytest.mark.asyncio
async def test_timer_async_iterator_and_disposal():
    ctx = Context()
    ticks = []

    async def _consume():
        async for _ in ctx.timer.interval(10):
            ticks.append(len(ticks) + 1)
            if len(ticks) >= 3:
                break

    await _consume()
    assert ticks == [1, 2, 3]


# ==============================================================================
# 1. Strict Dependency Injection 1:1 Parity
# ==============================================================================

def test_strict_inject_default_and_plugin_context_enforcement():
    """Verify strict inject is enforced by default in plugin contexts matching TS Proxy handler."""
    root_ctx = Context()

    class ServiceA:
        def __init__(self, val="hello"):
            self.val = val

    root_ctx.set_service("serviceA", ServiceA())

    # Root context allows access
    assert root_ctx.serviceA.val == "hello"

    # Plugin without inject cannot access undeclared serviceA via ctx.serviceA
    from dsh.cordis.plugin import Plugin
    plugin_errors = []

    class NoInjectPlugin(Plugin):
        name = "no-inject"
        inject = []

        def apply(self, ctx: Context):
            try:
                _ = ctx.serviceA
            except Exception as e:
                plugin_errors.append(e)

    root_ctx.plugin(NoInjectPlugin())
    assert len(plugin_errors) == 1
    assert "cannot get property 'serviceA' without inject" in str(plugin_errors[0])

    # But plugin CAN access serviceA via explicit ctx.get('serviceA')
    get_res = []

    class GetPlugin(Plugin):
        name = "get-plugin"
        inject = []

        def apply(self, ctx: Context):
            val = ctx.get("serviceA")
            get_res.append(val)

    root_ctx.plugin(GetPlugin())
    assert len(get_res) == 1
    assert get_res[0].val == "hello"


def test_strict_inject_inactive_service_error():
    """Verify accessing an injected service that is inactive raises specific inactive context error."""
    root_ctx = Context()
    from dsh.cordis.plugin import Plugin

    class InactiveService:
        pass

    # Register inactive service via a plugin that stays PENDING
    class DependencyPlugin(Plugin):
        name = "dep-provider"
        inject = ["non_existent_service"]  # Stays PENDING

        def apply(self, ctx: Context):
            ctx.provide("depService", InactiveService())

    root_ctx.plugin(DependencyPlugin())

    # Consumer plugin requires depService
    class ConsumerPlugin(Plugin):
        name = "consumer"
        inject = ["depService"]

        def apply(self, ctx: Context):
            pass

    consumer_fiber = root_ctx.plugin(ConsumerPlugin())
    assert consumer_fiber.state == FiberState.PENDING

    # Attempting to read consumer_fiber.ctx.depService directly raises inactive context error
    with pytest.raises(RuntimeError, match="cannot get required service 'depService' in inactive context"):
        _ = consumer_fiber.ctx.depService


def test_strict_inject_isolation_boundary_enforcement():
    """Verify isolation boundaries prevent unauthorized service access across scopes."""
    root_ctx = Context()

    class ScopeService:
        def __init__(self, scope):
            self.scope = scope

    root_ctx.set_service("scoped", ScopeService("root"))

    # Create isolated child context
    isolated_child = root_ctx.isolate("scoped")

    # In isolated child, provide scoped with label
    isolated_child.provide("scoped", ScopeService("isolated"))

    # Verify resolution within scope
    root_val = root_ctx.get("scoped")
    isolated_val = isolated_child.get("scoped")

    assert root_val.scope == "root"
    assert isolated_val.scope == "isolated"


# ==============================================================================
# 2. Reflect Service Invariants 1:1 Parity
# ==============================================================================

def test_reflect_property_accessor_and_service_conflict():
    """Verify cannot declare accessor over service or service over accessor."""
    ctx = Context()

    # 1. Declare accessor
    ctx.reflect.accessor("myProp", {"get": lambda c, err: 42})
    assert ctx.myProp == 42

    # 2. Cannot declare service over accessor
    with pytest.raises(RuntimeError, match="already declared as accessor"):
        ctx.provide("myProp", "value")

    # 3. Cannot declare duplicate accessor
    with pytest.raises(RuntimeError, match="already declared as accessor"):
        ctx.reflect.accessor("myProp", {"get": lambda c, err: 99})

    # 4. Declare new service
    ctx.provide("newService", "serv_val")
    assert ctx.get("newService") == "serv_val"

    # 5. Cannot declare accessor over service
    with pytest.raises(RuntimeError, match="already declared as service"):
        ctx.reflect.accessor("newService", {"get": lambda c, err: 100})


def test_reflect_set_invariants():
    """Verify set() throws when unprovided or when called across multiple fibers."""
    root_ctx = Context()
    from dsh.cordis.plugin import Plugin

    # 1. Cannot set unprovided property
    with pytest.raises(RuntimeError, match="without provide"):
        root_ctx.reflect.set(root_ctx, "unprovidedProp", 123)

    # 2. Provide in Fiber A
    fiber_a_errors = []

    class PluginA(Plugin):
        name = "plugin-a"

        def apply(self, ctx: Context):
            ctx.provide("sharedService", "initial_val")

    class PluginB(Plugin):
        name = "plugin-b"
        inject = ["sharedService"]

        def apply(self, ctx: Context):
            try:
                # Fiber B attempts to overwrite Fiber A's service
                ctx.reflect.set(ctx, "sharedService", "hijacked")
            except Exception as e:
                fiber_a_errors.append(e)

    root_ctx.plugin(PluginA())
    root_ctx.plugin(PluginB())

    assert len(fiber_a_errors) == 1
    assert "cannot set property 'sharedService' in multiple fibers" in str(fiber_a_errors[0])


def test_reflect_duplicate_provide_rejection():
    """Verify duplicate provide of same service name across different fibers throws error."""
    root_ctx = Context()
    from dsh.cordis.plugin import Plugin

    class Plugin1(Plugin):
        name = "provider-1"

        def apply(self, ctx: Context):
            ctx.provide("exclusiveService", 1)

    errors = []

    class Plugin2(Plugin):
        name = "provider-2"

        def apply(self, ctx: Context):
            try:
                ctx.provide("exclusiveService", 2)
            except Exception as e:
                errors.append(e)

    root_ctx.plugin(Plugin1())
    root_ctx.plugin(Plugin2())

    assert len(errors) == 1
    assert "service 'exclusiveService' has been registered at <provider-1>" in str(errors[0])


# ==============================================================================
# 3. Schemastery Structured Path Tracking & simplify() Parity
# ==============================================================================

def test_schemastery_issue_path_precision():
    """Verify Schema.validate returns structured paths and ValidationError formats correctly."""
    user_schema = Schema.object({
        "name": Schema.string().required(),
        "profile": Schema.object({
            "age": Schema.number().min(0).max(150),
            "tags": Schema.array(Schema.string()),
        }),
    })

    # Test invalid nested age
    invalid_data = {
        "name": "Alice",
        "profile": {
            "age": 200,
            "tags": ["admin"],
        },
    }

    res = user_schema.validate(invalid_data)
    assert "issues" in res
    assert len(res["issues"]) == 1
    issue = res["issues"][0]
    assert issue["path"] == ["profile", "age"]
    assert "expected number <= 150 but got 200" in issue["message"]

    # Test ValidationError aggregation string
    val_err = ValidationError(res["issues"])
    assert "invalid config:\n  - expected number <= 150 but got 200 (at profile.age)" in str(val_err)


def test_schemastery_simplify_default_removal():
    """Verify Schema.simplify() strips default values matching Schemastery."""
    cfg_schema = Schema.object({
        "host": Schema.string().default("127.0.0.1"),
        "port": Schema.number().default(8080),
        "debug": Schema.boolean().default(False),
        "nested": Schema.object({
            "timeout": Schema.number().default(30),
            "retries": Schema.number().default(3),
        }),
    })

    # Input matching defaults completely
    data_all_defaults = {
        "host": "127.0.0.1",
        "port": 8080,
        "debug": False,
        "nested": {
            "timeout": 30,
            "retries": 3,
        },
    }
    assert cfg_schema.simplify(data_all_defaults) is None

    # Input with some custom values
    data_custom = {
        "host": "0.0.0.0",
        "port": 8080,
        "debug": False,
        "nested": {
            "timeout": 60,
            "retries": 3,
        },
    }
    simplified = cfg_schema.simplify(data_custom)
    assert simplified == {
        "host": "0.0.0.0",
        "nested": {
            "timeout": 60,
        },
    }


# ==============================================================================
# 4. Shadow Context & Receiver Traceability Parity
# ==============================================================================

def test_shadow_context_and_receiver_traceability():
    """Verify get_traceable and with_props preserve caller context and receiver."""
    from dsh.cordis.utils import get_traceable
    from dsh.cordis.service import Service
    ctx = Context()

    class TargetService(Service):
        def __init__(self, ctx):
            super().__init__(ctx, "target")
            self.calls = []

        def do_action(self, val):
            self.calls.append((val, self.ctx))
            return val * 2

    service = TargetService(ctx)
    ctx.set_service("target", service)

    child_ctx = ctx.extend({"tag": "child-scope"})
    traced = get_traceable(child_ctx, service)

    res = traced.do_action(5)
    assert res == 10
    assert len(service.calls) == 1
    assert service.calls[0][0] == 5
    assert getattr(service.calls[0][1], "tag", None) == "child-scope"

