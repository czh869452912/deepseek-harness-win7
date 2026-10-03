"""
Unit tests covering ACP Tool Approval Lifecycle and MCP Declaration Normalization
Matching reference/packages/acp/acp/tests/approval.spec.ts and mcp.spec.ts
"""

import asyncio
import pytest
from dsh.acp.mcp import AcpMcpConfigError, entries_to_record, normalize_server_name

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


@pytest.mark.parametrize('name,expected', [('simple', 'simple'), ('_', '_'),
    ('Fancy server!', 'Fancy_server_fc5fd8aa'), ('!!!', 'server_e84c538e'),
    ('é café', 'e_cafe_47c57b29'), ('中文', 'server_72726d88'),
    ('😀', 'server_f0443a34'), ('\ud800', 'server_83d544cc')])
def test_mcp_server_name_uses_the_actual_acp_provider(name, expected):
    assert normalize_server_name(name) == expected


@pytest.mark.parametrize('entries,kind', [
    ([{'name': 'A', 'value': '1'}, {'name': 'A', 'value': '2'}], 'environment'),
    ([{'name': 'X-Key', 'value': 'one'}, {'name': 'x-key', 'value': 'two'}], 'header'),
])
def test_mcp_actual_provider_rejects_duplicate_environment_and_headers(entries, kind):
    with pytest.raises(AcpMcpConfigError, match='duplicate name'):
        entries_to_record(entries, 'mcpServers[0].entries', kind)


@pytest.mark.parametrize('entry', [{'name': '', 'value': '1'}, {'name': 'BAD=NAME', 'value': '1'},
    {'name': 'A\0', 'value': '1'}, {'name': 'A', 'value': '1\0'}])
def test_mcp_actual_provider_rejects_invalid_environment(entry):
    with pytest.raises(AcpMcpConfigError, match='invalid environment entry'):
        entries_to_record([entry], 'mcpServers[0].env', 'environment')


@pytest.mark.parametrize('kind', ['header', 'environment'])
def test_mcp_actual_provider_preserves_prototype_named_entries(kind):
    assert entries_to_record([{'name': '__proto__', 'value': 'safe data'}], 'entries', kind) == {
        '__proto__': 'safe data'}
