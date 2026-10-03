"""
ACP Server & Plugin matching reference/packages/acp/acp/src/index.ts
"""
import uuid
import inspect
import ntpath
import asyncio
import os
from typing import Any, Callable, Dict, List, Optional
from dsh.acp.codec import turn_end_to_stop_reason
from dsh.acp.content import AcpContentError, admit_acp_prompt, assistant_block_to_acp, supports_acp_image_prompts
from dsh.cordis.plugin import Plugin
from dsh.core.agent import AgentOptions
from dsh.core.abort import AbortController, abort_reason_error
from dsh.llm.error import error_chain
from dsh.acp.session_controls import decode_cursor, encode_cursor, field, resolve_page_size, same_directory, utf8_key


class SessionRecord:
    def __init__(self, agent: Any, dispose_fn: Optional[Callable[[], Any]] = None):
        self.agent = agent
        self.dispose_fn = dispose_fn
        self.inflight_prompt: Optional[Dict[str, Any]] = None
        self.closing: Optional[asyncio.Task] = None


class AcpPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-acp`: Automation-only Agent Client Protocol server bridge.
    """
    id = "acp"
    name = "@deepseek-ai/dsh-acp"
    inject = ["agents", "llm", "sessionPersistence", "sessions"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.config = config or {}
        self.sessions: Dict[str, SessionRecord] = {}
        self.closed: bool = False
        self.image_prompt_enabled: bool = False
        self.session_page_size = resolve_page_size(self.config.get('sessionListPageSize', 100))
        self.activating = set()
        self._lifetime = AbortController()
        self._closing: Optional[asyncio.Task] = None

    def apply(self, ctx: Any) -> None:
        if hasattr(ctx, "on"):
            ctx.on("session/event", self._on_session_event)
            ctx.on("agent/inbox/claimed", self._on_inbox_claimed)
            ctx.on("agent/error", self._on_agent_error)
            ctx.on("approval/request", self._on_approval_request)

        async def disposer():
            await self.close(ctx)

        if hasattr(ctx, "disposable"):
            ctx.disposable(disposer, label="acp.disposer")
        elif hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer)

    async def initialize(self, ctx: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        p = self.config.get("provider")
        m = self.config.get("model")
        self.image_prompt_enabled = supports_acp_image_prompts(ctx, p, m)
        return {
            "protocolVersion": 1,
            "agentInfo": {"name": "deepseek-harness-acp", "version": "0.0.1"},
            "agentCapabilities": {
                "sessionCapabilities": {"close": {}, "list": {}, "resume": {}},
                "promptCapabilities": {
                    "image": self.image_prompt_enabled,
                    "audio": False,
                    "embeddedContext": False,
                }
            },
            "authMethods": [],
        }

    async def authenticate(self, ctx: Any, params: Dict[str, Any]) -> None:
        pass

    def _assert_open(self, signal=None):
        if self.closed:
            raise RuntimeError('the ACP bridge has been disposed')
        if signal is not None and signal.aborted:
            raise abort_reason_error(signal)

    def _workspace(self, params):
        cwd = params.get("cwd", "")
        if not isinstance(cwd, str) or not (ntpath.isabs(cwd) or os.path.isabs(cwd)):
            raise ValueError("cwd must be an absolute path: %s" % cwd)
        if params.get("additionalDirectories"):
            raise ValueError("additionalDirectories is not supported")
        if params.get("mcpServers"):
            raise ValueError("mcpServers is not supported")
        return cwd

    def _operation(self, signal):
        controller = AbortController()
        remove = [self._lifetime.signal.add_listener('abort', controller.abort)]
        if signal is not None:
            remove.append(signal.add_listener('abort', controller.abort))
        def cleanup():
            for detach in remove:
                detach()
        try:
            self._assert_open(controller.signal)
        except BaseException:
            cleanup()
            raise
        return controller.signal, cleanup

    def _providers(self, ctx):
        agents, persistence, sessions = ctx.get('agents'), ctx.get('sessionPersistence'), ctx.get('sessions')
        if agents is None or persistence is None or sessions is None:
            raise RuntimeError('ACP requires agents, sessionPersistence and sessions providers')
        return agents, persistence, sessions

    def _require_session(self, session_id):
        self._assert_open()
        record = self.sessions.get(session_id)
        if record is None:
            raise ValueError('unknown session: %s' % session_id)
        if record.closing is not None:
            raise ValueError('session is closing')
        return record

    async def new_session(self, ctx: Any, params: Dict[str, Any], signal=None) -> Dict[str, Any]:
        self._assert_open(signal)
        cwd = self._workspace(params)
        agents, persistence, sessions = self._providers(ctx)
        session_id = str(uuid.uuid4())
        operation, cleanup = self._operation(signal)
        record = None
        try:
            handle = await agents.create(session_id=session_id, meta={'cwd': cwd},
                options=AgentOptions(provider=self.config.get('provider'), model=self.config.get('model')),
                signal=operation)
            record = SessionRecord(getattr(handle, 'agent', None), getattr(handle, 'dispose', None))
            self._assert_open(operation)
            if (record.agent is None or getattr(getattr(record.agent, 'session', None), 'id', None) != session_id
                    or not callable(record.dispose_fn)):
                raise RuntimeError('ACP agent factory returned an invalid owned handle')
            await persistence.ensure_materialized(record.agent.session)
            self._assert_open(operation)
            self.sessions[session_id] = record
            return {'sessionId': session_id}
        except BaseException:
            if record is not None:
                await asyncio.shield(self._begin_close(ctx, record))
            raise
        finally:
            cleanup()

    async def list_sessions(self, ctx: Any, params: Dict[str, Any], signal=None) -> Dict[str, Any]:
        self._assert_open(signal)
        cwd = params.get('cwd')
        if cwd is not None and (not isinstance(cwd, str) or not (ntpath.isabs(cwd) or os.path.isabs(cwd))):
            raise ValueError('cwd must be an absolute path: %s' % cwd)
        cursor = decode_cursor(params.get('cursor'))
        agents, persistence, sessions = self._providers(ctx)
        headers = await persistence.list()
        self._assert_open(signal)
        entries = []
        for header in headers:
            session_id, directory = field(header, 'id'), field(header, 'cwd')
            if (session_id in self.sessions or session_id in self.activating or sessions.get(session_id) is not None
                    or field(header, 'origin') == 'subagent' or field(header, 'parentSession') is not None
                    or not isinstance(directory, str) or not (ntpath.isabs(directory) or os.path.isabs(directory))):
                continue
            if cwd is not None and not same_directory(directory, cwd):
                continue
            entries.append((field(header, 'createdAt'), session_id, directory))
        entries.sort(key=lambda entry: (-entry[0], utf8_key(entry[1])))
        if cursor is not None:
            entries = [entry for entry in entries if entry[0] < cursor[0]
                       or (entry[0] == cursor[0] and utf8_key(entry[1]) > utf8_key(cursor[1]))]
        page = entries[:self.session_page_size]
        result = {'sessions': [{'sessionId': entry[1], 'cwd': entry[2]} for entry in page]}
        if len(entries) > len(page):
            result['nextCursor'] = encode_cursor(page[-1][0], page[-1][1])
        return result

    async def resume_session(self, ctx: Any, params: Dict[str, Any], signal=None) -> Dict[str, Any]:
        self._assert_open(signal)
        cwd = self._workspace(params)
        session_id = params.get('sessionId')
        agents, persistence, sessions = self._providers(ctx)
        if session_id in self.sessions or session_id in self.activating or sessions.get(session_id) is not None:
            raise ValueError('session is already active: %s' % session_id)
        operation, cleanup = self._operation(signal)
        self.activating.add(session_id)
        record = None
        try:
            headers = await persistence.list()
            self._assert_open(operation)
            header = next((item for item in headers if field(item, 'id') == session_id), None)
            if header is None or field(header, 'origin') == 'subagent' or field(header, 'parentSession') is not None:
                raise ValueError('session is not resumable: %s' % session_id)
            if not same_directory(field(header, 'cwd'), cwd):
                raise ValueError('session cwd does not match: %s' % cwd)
            handle = await agents.resume(resume_session_id=session_id,
                options=AgentOptions(provider=self.config.get('provider'), model=self.config.get('model')),
                signal=operation)
            record = SessionRecord(getattr(handle, 'agent', None), getattr(handle, 'dispose', None))
            self._assert_open(operation)
            if (record.agent is None or getattr(getattr(record.agent, 'session', None), 'id', None) != session_id
                    or not callable(record.dispose_fn)):
                raise RuntimeError('ACP agent factory returned an invalid owned handle')
            if not same_directory(field(record.agent.session.header, 'cwd'), cwd):
                raise ValueError('session cwd does not match: %s' % cwd)
            self.sessions[session_id] = record
            return {}
        except BaseException:
            if record is not None:
                await asyncio.shield(self._begin_close(ctx, record))
            raise
        finally:
            self.activating.discard(session_id)
            cleanup()

    def _begin_close(self, ctx, record):
        if record.closing is not None:
            return record.closing
        failures = []
        if record.inflight_prompt is not None:
            record.inflight_prompt['cancel_requested'] = True
            record.inflight_prompt['stop_reason'] = 'cancelled'
        if record.agent is not None and hasattr(record.agent, 'cancel'):
            try:
                record.agent.cancel({'kind': 'user'})
            except Exception as error:
                failures.append(error)

        async def drain():
            async def attempt(operation):
                try:
                    result = operation()
                    if inspect.isawaitable(result):
                        await result
                except Exception as error:
                    failures.append(error)
            if record.agent is not None and callable(record.dispose_fn):
                if hasattr(record.agent, 'when_idle'):
                    await attempt(record.agent.when_idle)
                subagents = ctx.get('subagents')
                if subagents is not None:
                    await attempt(lambda: subagents.drainContinuableDescendants([record.agent]))
                sessions = ctx.get('sessions')
                if sessions is not None:
                    await attempt(lambda: sessions.flush(record.agent.session))
            if callable(record.dispose_fn):
                await attempt(record.dispose_fn)
            if failures:
                raise RuntimeError('ACP session teardown failed: ' + '; '.join(error_chain(error) for error in failures))
        record.closing = asyncio.create_task(drain())
        return record.closing

    async def close_session(self, ctx: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        self._assert_open()
        session_id = params.get('sessionId')
        record = self.sessions.get(session_id)
        if record is None:
            raise ValueError('unknown session: %s' % session_id)
        try:
            await asyncio.shield(self._begin_close(ctx, record))
            return {}
        except Exception as error:
            raise RuntimeError('session close failed: %s' % error) from error
        finally:
            def remove_record(completed):
                if not completed.cancelled():
                    completed.exception()
                if self.sessions.get(session_id) is record:
                    del self.sessions[session_id]
            if record.closing.done():
                remove_record(record.closing)
            else:
                record.closing.add_done_callback(remove_record)

    async def close(self, ctx):
        if self._closing is None:
            self.closed = True
            self._lifetime.abort(RuntimeError('the ACP bridge has been disposed'))
            records = list(self.sessions.items())
            pending = [self._begin_close(ctx, record) for session_id, record in records]
            async def drain_all():
                results = await asyncio.gather(*pending, return_exceptions=True)
                for session_id, record in records:
                    if self.sessions.get(session_id) is record:
                        del self.sessions[session_id]
                failures = [result for result in results if isinstance(result, BaseException)]
                if failures:
                    raise RuntimeError('ACP agent teardown failed for %s session(s): %s' % (
                        len(failures), '; '.join(error_chain(error) for error in failures)))
            self._closing = asyncio.create_task(drain_all())
        await asyncio.shield(self._closing)

    async def prompt(self, ctx: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        session_id = params.get("sessionId")
        rec = self._require_session(session_id)
        if rec.inflight_prompt is not None:
            raise ValueError("a prompt is already in flight for this session")

        prompt_blocks = params.get("prompt", [])
        content = admit_acp_prompt(ctx, rec.agent, prompt_blocks, self.image_prompt_enabled)

        msg = {"id": f"msg-{uuid.uuid4().hex[:8]}", "role": "user", "content": content}
        inflight = {"msg_id": msg["id"], "turn": None, "stop_reason": "end_turn",
                    "cancel_requested": False, "end_reason": None, "agent_error": None}
        rec.inflight_prompt = inflight
        try:
            if rec.agent and hasattr(rec.agent, "followup"):
                rec.agent.followup(msg)

            if rec.agent and hasattr(rec.agent, "when_idle"):
                result = rec.agent.when_idle()
                if inspect.isawaitable(result):
                    await result

            if inflight["cancel_requested"]:
                return {"stopReason": "cancelled"}
            if inflight["agent_error"] is not None:
                raise RuntimeError("turn failed: %s" % inflight["agent_error"])
            reason = inflight["end_reason"]
            if reason is not None and reason.get("kind") == "error":
                error = reason.get("error")
                detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                raise RuntimeError("turn failed: %s" % detail)
            if rec.agent is not None and reason is None:
                return {"stopReason": "cancelled"}
            return {"stopReason": inflight["stop_reason"]}
        finally:
            if rec.inflight_prompt is inflight:
                rec.inflight_prompt = None

    async def cancel(self, ctx: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        if session_id in self.sessions:
            rec = self.sessions[session_id]
            if rec.inflight_prompt:
                rec.inflight_prompt["cancel_requested"] = True
                rec.inflight_prompt["stop_reason"] = "cancelled"
            if rec.agent and hasattr(rec.agent, "cancel"):
                rec.agent.cancel({"kind": "user"})

    def _on_session_event(self, session: Any, event: Dict[str, Any]) -> None:
        e_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
        data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
        rec = self.sessions.get(getattr(session, "id", None))
        if rec is None or getattr(rec.agent, "session", None) is not session:
            return
        inflight = rec.inflight_prompt
        if (e_type == "turn/end" and isinstance(data, dict) and inflight is not None
                and inflight.get("turn") is not None and inflight["turn"] == data.get("turn")):
            reason = data.get("reason", {})
            inflight["end_reason"] = reason
            inflight["stop_reason"] = turn_end_to_stop_reason(reason)

    def _owned_agent_record(self, agent: Any) -> Optional[SessionRecord]:
        session = getattr(agent, "session", None)
        rec = self.sessions.get(getattr(session, "id", None))
        return rec if rec is not None and rec.agent is agent else None

    def _on_inbox_claimed(self, payload: Dict[str, Any]) -> None:
        rec = self._owned_agent_record(payload.get("agent"))
        if (rec is not None and rec.inflight_prompt is not None
                and rec.inflight_prompt["msg_id"] == payload.get("message", {}).get("id")):
            rec.inflight_prompt["turn"] = payload.get("turn")

    def _on_agent_error(self, payload: Dict[str, Any]) -> None:
        rec = self._owned_agent_record(payload.get("agent"))
        if rec is not None and rec.inflight_prompt is not None:
            inflight = rec.inflight_prompt
            if inflight.get("turn") != payload.get("turn"):
                inflight["agent_error"] = payload.get("error")

    def _on_approval_request(self, request: Any, next_fn: Any) -> Any:
        return next_fn()
