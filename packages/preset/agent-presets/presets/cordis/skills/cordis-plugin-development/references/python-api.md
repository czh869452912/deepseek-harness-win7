# Python bindings and lifecycle

Read this for Host service/event calls, dependencies, cleanup, timers and tools. Inspect the specific provider before using methods absent from these examples.

## Dynamic versus native API

Dynamic code declares callable plugin in code.host. harness is injected into that source namespace, not imported from a package. ctx exposes get, tools, provide, effect, on/once and supported timer helpers. Hard dependencies belong on plugin.inject; attribute service access requires injection. Optional ctx.get checks None. Avoid runtime internals and importing full Context to bypass the facade.

Native source packages import Plugin from dsh.plugin_api and implement apply(self, ctx, config). Their full Context supports set_service, but registrations should still use lifecycle ownership. Do not paste native class source into cordis_define or paste dynamic harness references into an ordinary module without the packaged-source adapter.

## Type and calling boundaries

- TS interfaces describe names, parameters and wire shape; use Python dictionaries/lists for JSON records/arrays. Python True/False/None are not JS true/false/null source literals.
- Missing optional ctx.get services use None. Some core protocol paths distinguish the supplied UNDEFINED sentinel from None. Preserve that distinction where the actual provider requires it; do not mechanically replace undefined in every upstream signature.
- The Host has restricted computation imports, not arbitrary Python imports. Query Host Builtins for the current list. open, filesystem/process/network/thread modules and direct event-loop access are unavailable. eval/exec retain the same restricted builtins, including when supplied an empty globals dictionary; compile remains available for computation. Use inspected Context services and reversible effects. asyncio provides selected coordination primitives; asyncio.sleep(0) yields, while delays use ctx.timeout(milliseconds) after declaring plugin.inject = ['timer'].
- Await actual async Python methods in async callbacks. A TS Promise label alone does not determine the implementation's Python calling convention. Do not use asyncio.run inside the running Host loop.
- harness.handle accepts a sync or async function of JSON args. Return only supported JSON data; NaN, negative zero and live objects are not portable RPC payloads.
- Dynamic tool execute receives (args, execution); output.render receives (args, value) and returns content blocks. Respect execution.signal on long-running work using its actual abort contract.

## Executable minimal tool

Use [echo.host.py](../examples/echo.host.py) unchanged to start. Dynamic parameters are a schema-property map, for example {'text': {'type': 'string', 'required': True}}. Native tools use the complete {'type': 'object', 'properties': ..., 'required': ['text']} root. The dynamic output value DSL also puts required: True on each required object property, as in counter.host.py, not a required list on the object. Query the harness contract rather than mixing both DSLs.

defineTool marks and validates its returned definition. Both ctx.tools.register and harness.registerTool(ctx, tool) enforce that marker. A successful output renderer must return an array such as [{'type': 'text', 'text': value}]. Wrong parameters or wrong output shape are execution failures, not a reason to disable validation.

## Effects and async work

ctx.effect takes setup, and setup returns cleanup:

```python
def plugin(ctx):
    def setup():
        resource = acquire_resource()  # your own implementation
        return resource.close
    ctx.effect(setup)
```

The acquire_resource name is a pattern placeholder, not a Host builtin. For an existing cleanup use ctx.effect(lambda: cleanup). Calling ctx.effect(cleanup) executes cleanup during activation and does not retain it as teardown.

The outer function must return the disposer, not call it. For state dictionaries use ctx.effect(lambda: state.clear), without parentheses after clear. ctx.effect(lambda: state.clear()) immediately empties the state; a later RPC can then fail with a missing key. Owned effects unwind in reverse registration order, and async teardown is awaited. Use the linked executable examples before reverse engineering disposal internals.

For a separately started Python task:

```python
import asyncio

def plugin(ctx):
    async def work():
        await ctx.timeout(60000)

    task = asyncio.create_task(work())

    async def cleanup():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    ctx.effect(lambda: cleanup)

plugin.inject = ['timer']
```

Own external subscriptions through their disposer. Cordis cannot remove arbitrary callbacks or process-global changes that were never registered with its lifecycle. Plugin top-level definitions may be evaluated before activation; put resource acquisition in plugin, not module scope.

## Events and timers

Use [lifecycle.host.py](../examples/lifecycle.host.py) as an executable example of owned custom events, a timer and async cleanup. Its win7-authoring/* events are example-defined names, not claims about built-in system events. For a real system event query Event.listEvents and preserve its actual callback arguments/mode.

An ordinary callback handles emit notification. Serial and parallel listeners may be async. Waterfall callbacks receive next last and return/await next() according to the provider contract; do not forget downstream processing. Register with ctx.on rather than reaching for the event bus. The dynamic facade does not expose emit/parallel/serial/waterfall dispatch internals.

Timer helpers need plugin.inject = ['timer']. Delays are milliseconds. ctx.timeout and ctx.interval register owned effects. A Python standard-library timer is not automatically a Cordis timer. For client React effects, return the supported service timer disposer from useEffect; do not invent a global setTimeout.

## Dependencies and scope

When a required provider disappears, Cordis withdraws dependent contributions; returning providers trigger fresh activation. Inspect waiting state and do not report a waiting package as running. Re-read services per activation; old handlers/references must not continue succeeding after stop/update/unload.

Publish dynamic services with ctx.provide. A standing preset may share its state between agents; different presets or a directly scoped Agent extension have different ownership. Test the intended topology rather than assuming one instance per conversation. A hard dependency supplied by the same plugin causes waiting rather than activating itself.
