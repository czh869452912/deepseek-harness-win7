"""
Message value types, identity, and construction helpers.
Aligned 1:1 with official `@deepseek-ai/dsh-llm/message.ts`.
"""

import copy
import os
import uuid
from typing import Any, Dict, List, Optional, Union


def random_uuid() -> str:
    return str(uuid.uuid4())


def freeze_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Detach snapshot of a message preserving identity."""
    return copy.deepcopy(message)


freezeMessage = freeze_message


def create_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create one identified message before publication.
    """
    res = dict(input_data)
    if "id" not in res:
        res["id"] = f"msg-{random_uuid()}"
    return freeze_message(res)


createMessage = create_message


def create_user_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create one identified user-role message.
    """
    res = dict(input_data)
    res["role"] = "user"
    if "source" not in res:
        res["source"] = {"kind": "user"}
    if "content" in res and isinstance(res["content"], str):
        res["content"] = [{"type": "text", "text": res["content"]}]
    return create_message(res)


createUserMessage = create_user_message


def create_assistant_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create one identified model-produced assistant message.
    """
    res = dict(input_data)
    res["role"] = "assistant"
    raw_source = dict(res.get("source", {})) if isinstance(res.get("source"), dict) else {}
    raw_source["kind"] = "model"
    if "provider" not in raw_source:
        raw_source["provider"] = "mock"
    if "model" not in raw_source:
        raw_source["model"] = "mock"
    res["source"] = raw_source

    content = res.get("content", [])
    if isinstance(content, str):
        res["content"] = [{"type": "text", "text": content}] if content else []
    return create_message(res)


createAssistantMessage = create_assistant_message


def create_tool_result_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create one identified tool-result message in user role.
    """
    call_id = input_data.get("callId") or input_data.get("call_id") or input_data.get("toolCallId") or "call-1"
    raw_content = input_data.get("content", [])
    if isinstance(raw_content, str):
        content_blocks = [{"type": "text", "text": raw_content}]
    elif isinstance(raw_content, list):
        content_blocks = [
            {"type": "text", "text": item} if isinstance(item, str) else item
            for item in raw_content
        ]
    else:
        content_blocks = []

    is_error = bool(input_data.get("isError", input_data.get("is_error", False)))

    return create_user_message({
        "source": {"kind": "tool", "callId": call_id},
        "content": [{
            "type": "tool-result",
            "toolCallId": call_id,
            "content": content_blocks,
            "isError": is_error,
        }],
    })


createToolResultMessage = create_tool_result_message
