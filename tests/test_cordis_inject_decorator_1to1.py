"""
1:1 Unit tests for @inject decorator in Cordis
Matching reference/vendor/cordis/src/registry.ts
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.registry import inject, Inject


def test_inject_class_decorator():
    @inject(["tools", "fs"])
    class MyPlugin(Plugin):
        name = "my_plugin"

    assert isinstance(MyPlugin.inject, dict)
    assert "tools" in MyPlugin.inject
    assert "fs" in MyPlugin.inject

    @inject("llm", {"model": "deepseek-chat"})
    class LlmConsumer(Plugin):
        name = "llm_consumer"

    assert LlmConsumer.inject["llm"] == {"model": "deepseek-chat"}


def test_inject_method_decorator():
    class ServiceCaller:
        def __init__(self, ctx):
            self.ctx = ctx
            self.called = False

        @inject("tools")
        def execute_tool(self):
            self.called = True
            return "tool executed"

    ctx = Context()
    caller = ServiceCaller(ctx)

    # Calling without injected service defers execution via ctx.inject rather than throwing
    caller.execute_tool()
    assert not caller.called

    # Once service is provided, call succeeds
    ctx.set_service("tools", {"name": "dummy_tools"})
    assert caller.execute_tool() == "tool executed"
    assert caller.called


def test_inject_resolve_utility():
    res = Inject.resolve(["a", "b"])
    assert res == {"a": None, "b": None}

    res2 = Inject.resolve({"a": 1, "b": 2})
    assert res2 == {"a": 1, "b": 2}

    res3 = Inject.resolve("single")
    assert res3 == {"single": None}
