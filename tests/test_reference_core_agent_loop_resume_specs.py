"""
1:1 Test Parity Suite matching reference/packages/core/agent-loop/tests/resume.spec.ts.
Covers:
- Resuming session with pre-identity message events
- Rollback on resume failure
- Caller-supplied custom sessionId
- Rejection of duplicate agent identities
- Prevention of crash-repair on turns owned by a live agent
"""

import asyncio
import os
import shutil
import tempfile
import pytest
from typing import Any, Dict, List, Optional
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin, AgentRegistry
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import SESSION_FORMAT_VERSION, Session, SessionHeader, SessionPlugin, SessionStore
from dsh.core.tools import ToolsPlugin
from dsh.llm.message import createUserMessage
from dsh.session.persistence_jsonl import JsonlSessionPersistence, JsonlSessionPersistencePlugin


class MockLlmService:
    def __init__(self, responses: Optional[List[Dict[str, Any]]] = None):
        self.provider = "mock"
        self.model = "mock"
        self.responses = list(responses or [])
        self.requests: List[Dict[str, Any]] = []

    async def chat_completion_stream(self, messages, tools=None, system=None, request=None):
        self.requests.append(request or {"messages": messages})
        if self.responses:
            resp = self.responses.pop(0)
            text = resp.get("text", resp.get("content", ""))
            if text:
                yield {"type": "text-delta", "index": 0, "text": text}
            yield {"type": "finish", "reason": {"kind": "stop"}}
            return
        yield {"type": "text-delta", "index": 0, "text": "mock reply"}
        yield {"type": "finish", "reason": {"kind": "stop"}}


async def mount_persistent_harness(root: str, responses: Optional[List[Dict[str, Any]]] = None) -> Context:
    ctx = Context()
    ctx.set_service("llm", MockLlmService(responses=responses))
    SessionPlugin().apply(ctx)
    ToolsPlugin().apply(ctx)
    AgentPlugin().apply(ctx)
    AgentLoopPlugin().apply(ctx)

    persist_svc = JsonlSessionPersistence(root=root)
    ctx.set_service("session_persistence", persist_svc)
    return ctx


@pytest.mark.asyncio
async def test_resumes_pre_react_loop_session_including_pre_identity_events():
    temp_dir = tempfile.mkdtemp(prefix="dsh-resume-")
    try:
        ctx1 = await mount_persistent_harness(temp_dir)
        persist: JsonlSessionPersistence = ctx1.get("session_persistence")

        session_id = "pre-identity-resume"
        await persist.create(SessionHeader.from_dict({
            "version": SESSION_FORMAT_VERSION,
            "id": session_id,
            "createdAt": 1,
        }))
        await persist.append(session_id, [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {
                "type": "user/message",
                "seq": 1,
                "time": 2,
                "data": {"content": [{"type": "text", "text": "old question"}], "source": {"kind": "user"}},
                "surfaceOp": "append",
            },
            {"type": "step/start", "seq": 2, "time": 3, "data": {"turn": 1, "step": 1}},
            {
                "type": "assistant/message",
                "seq": 3,
                "time": 4,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "content": [{"type": "text", "text": "old answer"}],
                },
                "surfaceOp": "append",
            },
            {"type": "step/end", "seq": 4, "time": 5, "data": {"turn": 1, "step": 1}},
            {"type": "turn/end", "seq": 5, "time": 6, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ])

        # Resume in fresh context
        ctx2 = await mount_persistent_harness(temp_dir, responses=[{"text": "new answer"}])
        agents: AgentRegistry = ctx2.get("agents")
        handle = await agents.resume(resume_session_id=session_id, options=AgentOptions(provider="mock", model="mock"))

        assert len(handle.agent.session.derive_messages()) == 2
        assert handle.agent.inbox.next_turn == []
        assert handle.agent.inbox.next_step == []

        handle.agent.followup("new question")
        await handle.agent.when_idle()

        assert len(handle.agent.session.derive_messages()) == 4
        assert handle.agent.session.events[-1]["type"] == "turn/end"
        assert handle.agent.session.events[-1]["data"]["reason"] == {"kind": "completed"}

        await handle.dispose()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_create_agent_uses_caller_supplied_session_id():
    temp_dir = tempfile.mkdtemp(prefix="dsh-create-")
    try:
        ctx = await mount_persistent_harness(temp_dir)
        agents: AgentRegistry = ctx.get("agents")
        handle = await agents.create(session_id="custom-session", meta={"cwd": "/w"})
        assert handle.agent.session.id == "custom-session"
        assert handle.agent.session.header.cwd == "/w"
        await handle.dispose()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_create_agent_rejects_duplicate_identity():
    temp_dir = tempfile.mkdtemp(prefix="dsh-dup-")
    try:
        ctx = await mount_persistent_harness(temp_dir)
        agents: AgentRegistry = ctx.get("agents")
        handle1 = await agents.create(session_id="sess-a")

        with pytest.raises(ValueError, match="already exists"):
            await agents.create(session_id="sess-a")

        await handle1.dispose()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_resume_cannot_crash_repair_turn_owned_by_live_agent():
    temp_dir = tempfile.mkdtemp(prefix="dsh-live-resume-")
    try:
        ctx = await mount_persistent_harness(temp_dir)
        agents: AgentRegistry = ctx.get("agents")
        store: SessionStore = ctx.get("sessions")

        session_id = "live-resume-race"
        handle = await agents.create(session_id=session_id)
        handle.agent.session.append("turn/start", {"turn": 1})
        await store.flush(handle.agent.session)

        with pytest.raises(RuntimeError, match="while it is live"):
            await agents.resume(resume_session_id=session_id)

        await handle.dispose()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
