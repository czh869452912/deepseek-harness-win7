import pytest
from dsh.compaction.pruner import ToolResultPruner
from dsh.cordis.context import Context
from dsh.core.session import Session
from dsh.llm.token_meter import TokenMeter


def test_prune_content():
    pruner = ToolResultPruner(threshold_chars=20, head_chars=5, tail_chars=5)

    # Below threshold: no pruning
    assert pruner.prune_content("short text") is None

    # Above threshold: prune middle
    text = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    pruned = pruner.prune_content(text)
    assert pruned is not None
    assert pruned.startswith("01234")
    assert pruned.endswith("VWXYZ")
    assert "pruned" in pruned


def test_prune_session():
    ctx = Context()
    meter = TokenMeter(ctx)
    ctx.set_service("token_meter", meter)

    pruner = ToolResultPruner(threshold_chars=50, head_chars=10, tail_chars=10, ctx=ctx)
    ctx.set_service("tool_result_pruner", pruner)

    session = Session(session_id="prune-test-session", ctx=ctx)
    session.append_user_message("Run tool")
    session.append_assistant_message({
        "role": "assistant",
        "content": "Running tool",
        "tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": "{}"}}],
    })

    long_output = "LINE_" * 30  # 180 chars > 50 chars threshold
    tool_event = session.append_tool_result("c1", "read", long_output)
    tool_seq = tool_event["seq"]

    assert session.surface.nodes == [0, 1, 2]
    assert session.surface.replace_generation == 0

    # Execute pruning
    result = pruner.prune_session(session)
    assert result["chars_removed"] > 0
    assert len(result["pruned"]) == 1

    # Surface should now have replacement generation 1
    assert session.surface.replace_generation == 1
    assert session.surface.nodes[2] == 4  # seq 3 is compaction/prune, seq 4 is replacement tool/result

    # Derived message should contain the pruned content
    messages = session.derive_messages()
    tool_msg = messages[-1]
    assert tool_msg["role"] in ("tool", "user")
    assert "pruned" in str(tool_msg["content"])
