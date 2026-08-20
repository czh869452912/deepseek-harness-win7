import pytest
from dsh.cordis.context import Context


@pytest.mark.asyncio
async def test_cordis_bail_dispatch():
    ctx = Context()

    call_order = []

    def handler_1(data):
        call_order.append("h1")
        return None  # Pass through

    def handler_2(data):
        call_order.append("h2")
        return f"Handled by h2: {data}"  # Bail!

    def handler_3(data):
        call_order.append("h3")
        return f"Handled by h3: {data}"

    ctx.on("policy/check", handler_1)
    ctx.on("policy/check", handler_2)
    ctx.on("policy/check", handler_3)

    result = await ctx.bail("policy/check", "test_item")
    assert result == "Handled by h2: test_item"
    assert call_order == ["h1", "h2"]  # h3 was not called!


def test_cordis_scoped_context_hierarchy():
    root = Context()
    root.set_service("global_config", {"mode": "production"})

    child = root.extend()
    assert child.get("global_config") == {"mode": "production"}
    assert child.root == root

    # Register child-specific effect
    child_cleaned_up = []
    child.effect(lambda: child_cleaned_up.append(True))

    child.teardown()
    assert len(child_cleaned_up) == 1
    # Root remains valid
    assert root.get("global_config") == {"mode": "production"}


def test_cordis_isolated_context():
    root = Context()
    root.set_service("tools", "root_tools")
    root.set_service("logger", "root_logger")

    child = root.isolate(keys=["tools"])
    # 'tools' is isolated from parent
    assert child.get("tools") is None
    # 'logger' is still inherited
    assert child.get("logger") == "root_logger"
