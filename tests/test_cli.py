from unittest.mock import MagicMock
import pytest
from dsh.harness import build_harness


@pytest.mark.asyncio
async def test_mock_llm_turn_execution():
    # Build harness with mock LLM
    ctx = build_harness(mode="minimal")

    mock_llm = MagicMock()
    # Step 1: LLM decides to call tool 'str_replace_editor' command 'view'
    mock_llm.chat_completion.side_effect = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "str_replace_editor",
                        "arguments": '{"command": "view", "path": "."}'
                    }
                }
            ]
        },
        # Step 2: LLM returns final text response
        {
            "role": "assistant",
            "content": "I have inspected the directory contents.",
            "tool_calls": None
        }
    ]

    ctx.set_service("llm", mock_llm)

    agent_loop = ctx.get("agent_loop")
    response = await agent_loop.run_turn("Please view the current directory.")

    assert response == "I have inspected the directory contents."
    assert mock_llm.chat_completion.call_count == 2
    ctx.teardown()
