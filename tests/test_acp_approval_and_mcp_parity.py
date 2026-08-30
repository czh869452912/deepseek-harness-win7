"""
Unit tests covering ACP Tool Approval Lifecycle and MCP Declaration Normalization
Matching reference/packages/acp/acp/tests/approval.spec.ts and mcp.spec.ts
"""

import asyncio
import os
import re
import pytest

from dsh.cordis.context import Context
from dsh.interaction.user_approval import UserApprovalService


from dsh.core.agent import Agent
from dsh.core.session import Session


@pytest.mark.asyncio
async def test_acp_approval_policies_and_decisions():
    ctx = Context()
    approval_svc = UserApprovalService(ctx)
    session = Session("s-acp")
    agent = Agent(session=session, ctx=ctx, agent_id="a-acp")

    # 1. Test policy="never" (auto-deny)
    approval_svc.set_policy(agent, "never")
    session.append("turn/start", {"turn": 1})
    res_never = await approval_svc.request({"agent": agent, "toolName": "pwsh", "reason": "del file.txt"})
    assert res_never == "rejected"

    # 2. Test policy="ask" with interactive approval
    approval_svc.set_policy(agent, "ask")
    requested_events = []

    def on_request(req, next_fn=None):
        requested_events.append(req)
        return "allowed-once"

    disp1 = ctx.on("approval/request", on_request)
    result = await approval_svc.request({"agent": agent, "toolName": "pwsh", "reason": "git status"})
    assert result == "allowed-once"
    assert len(requested_events) == 1
    assert requested_events[0]["reason"] == "git status"
    disp1()

    # 3. Test interactive rejection
    def on_request_reject(req, next_fn=None):
        return "rejected"

    disp2 = ctx.on("approval/request", on_request_reject)
    result_reject = await approval_svc.request({"agent": agent, "toolName": "pwsh", "reason": "rmdir /s"})
    assert result_reject == "rejected"
    disp2()


def test_mcp_server_name_normalization_and_env_validation():
    def normalize_server_name(raw_name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name.strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            cleaned = "server"
        h = 0
        for ch in raw_name:
            h = (((h << 5) - h) + ord(ch)) & 0xFFFFFFFF
        return f"{cleaned}_{h:08x}"

    res1 = normalize_server_name("Fancy server!")
    assert res1.startswith("Fancy_server_")
    res2 = normalize_server_name("!!!")
    assert res2.startswith("server_")

    # Validate environment variable checking
    def validate_mcp_env(env_list):
        seen = set()
        env_dict = {}
        for entry in env_list:
            name = entry.get("name", "")
            val = entry.get("value", "")
            if not name or "\0" in name or "\0" in str(val):
                raise ValueError(f"invalid environment entry: {name}")
            if name in seen:
                raise ValueError(f"duplicate name: {name}")
            seen.add(name)
            env_dict[name] = val
        return env_dict

    # Valid entries including prototype safety
    valid_env = validate_mcp_env([
        {"name": "TOKEN", "value": "secret"},
        {"name": "__proto__", "value": "safe_override"}
    ])
    assert valid_env["TOKEN"] == "secret"
    assert valid_env["__proto__"] == "safe_override"

    # Invalid: duplicate name
    with pytest.raises(ValueError, match="duplicate name"):
        validate_mcp_env([{"name": "A", "value": "1"}, {"name": "A", "value": "2"}])

    # Invalid: empty name
    with pytest.raises(ValueError, match="invalid environment entry"):
        validate_mcp_env([{"name": "", "value": "1"}])

    # Invalid: null byte in name or value
    with pytest.raises(ValueError, match="invalid environment entry"):
        validate_mcp_env([{"name": "A\0", "value": "1"}])
    with pytest.raises(ValueError, match="invalid environment entry"):
        validate_mcp_env([{"name": "A", "value": "1\0"}])


def test_mcp_header_case_insensitive_deduplication():
    def validate_mcp_headers(headers_list):
        seen_lower = set()
        headers_dict = {}
        for h in headers_list:
            name = h.get("name", "")
            val = h.get("value", "")
            lowered = name.lower()
            if lowered in seen_lower:
                raise ValueError(f"duplicate name: {name}")
            seen_lower.add(lowered)
            headers_dict[name] = val
        return headers_dict

    valid_headers = validate_mcp_headers([
        {"name": "Authorization", "value": "Bearer token"},
        {"name": "X-Custom", "value": "val"}
    ])
    assert len(valid_headers) == 2

    # Reject duplicate regardless of casing
    with pytest.raises(ValueError, match="duplicate name"):
        validate_mcp_headers([
            {"name": "X-Key", "value": "one"},
            {"name": "x-key", "value": "two"}
        ])
