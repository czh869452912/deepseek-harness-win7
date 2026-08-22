"""
Unit tests for ACP plugin (dsh/acp) matching TypeScript reference
"""
import pytest
from dsh.acp import (
    AcpContentError,
    AcpPlugin,
    admit_acp_prompt,
    assistant_block_to_acp,
    supports_acp_image_prompts,
    turn_end_to_stop_reason,
)
from dsh.cordis.context import Context


def test_turn_end_to_stop_reason():
    assert turn_end_to_stop_reason({"kind": "completed"}) == "end_turn"
    assert turn_end_to_stop_reason({"kind": "max-tokens"}) == "max_tokens"
    assert turn_end_to_stop_reason({"kind": "interrupted"}) == "cancelled"
    assert turn_end_to_stop_reason({"kind": "error"}) == "end_turn"


def test_admit_acp_prompt_text_and_resource_link():
    ctx = Context()
    prompt = [
        {"type": "text", "text": "What is the capital of France?"},
        {"type": "resource_link", "name": "guide", "uri": "file:///guide.txt"},
    ]
    content = admit_acp_prompt(ctx, None, prompt)
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert "capital of France" in content[0]["text"]
    assert "resource_link" in content[0]["text"]


def test_admit_acp_prompt_invalid_image_when_not_enabled():
    ctx = Context()
    prompt = [{"type": "image", "mimeType": "image/png", "data": "aGVsbG8="}]
    with pytest.raises(AcpContentError) as exc_info:
        admit_acp_prompt(ctx, None, prompt, image_enabled=False)
    assert exc_info.value.kind == "invalid"
    assert "not advertised" in str(exc_info.value)


def test_admit_acp_prompt_unsupported_content():
    ctx = Context()
    prompt = [{"type": "audio", "data": "abc"}]
    with pytest.raises(AcpContentError):
        admit_acp_prompt(ctx, None, prompt)


def test_assistant_block_to_acp():
    ctx = Context()
    text_block = {"type": "text", "text": "Hello assistant response"}
    acp_out = assistant_block_to_acp(ctx, text_block)
    assert acp_out == {"type": "text", "text": "Hello assistant response"}


@pytest.mark.asyncio
async def test_acp_plugin_lifecycle():
    ctx = Context()
    plugin = AcpPlugin({"provider": "test_provider", "model": "test_model"})
    plugin.apply(ctx)

    init_res = await plugin.initialize(ctx, {})
    assert init_res["protocolVersion"] == "1.0"
    assert "agentCapabilities" in init_res

    session_res = await plugin.new_session(ctx, {"cwd": "D:\\Claude-project"})
    session_id = session_res["sessionId"]
    assert session_id in plugin.sessions

    # Test prompt
    prompt_res = await plugin.prompt(ctx, {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": "Hello"}]
    })
    assert prompt_res["stopReason"] == "end_turn"

    # Test cancel
    await plugin.cancel(ctx, {"sessionId": session_id})
