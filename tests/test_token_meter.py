import pytest
from dsh.core.session import Session
from dsh.llm.token_meter import (
    TokenMeter,
    estimate_content,
    estimate_header,
    estimate_message,
)


def test_estimate_content():
    # 4 chars per token + 4 overhead
    assert estimate_content("1234") == 1 + 4
    assert estimate_content("12345678") == 2 + 4

    # List of blocks
    blocks = [
        {"type": "text", "text": "1234"},
        {"type": "tool-call", "name": "read", "arguments": "{}"},
    ]
    tokens = estimate_content(blocks)
    assert tokens > 10


def test_estimate_message():
    msg = {
        "role": "user",
        "content": "Hello world!",
    }
    # Content tokens + ROLE_OVERHEAD (4)
    tokens = estimate_message(msg)
    assert tokens == estimate_content("Hello world!") + 4


def test_token_meter_measure_session():
    meter = TokenMeter()
    session = Session(session_id="test-meter-session")

    session.append_request_header({
        "system": "You are an assistant.",
        "tools": [{"name": "read_file"}],
        "config": {"provider": "openai", "model": "deepseek-chat"},
    })

    session.append_user_message("Please help me.")
    session.append_assistant_message({"role": "assistant", "content": "Sure, what do you need?"})

    measurement = meter.measure(session)
    assert measurement["total_tokens"] > 0
    assert measurement["header_tokens"] > 0
    assert measurement["surface_tokens"] > 0
    assert len(measurement["nodes"]) == 2  # 2 surface nodes (user, assistant)
    assert measurement["nodes"][0]["tokens"] > 0
    assert measurement["nodes"][1]["tokens"] > 0
