"""
Concrete Agent Loop Driver and Factory Service mounted at `ctx.agent_loop`.
1:1 aligned with official `@deepseek-ai/dsh-agent-loop`.
"""

import asyncio
import inspect
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.context import Context
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.plugin import Plugin
from dsh.core.agent import Agent, AgentHandle, AgentOptions, AgentRegistry
from dsh.core.scope import create_scope, ScopeKey, scope_of, scope_target
from dsh.core.runtime_context import RuntimeContextProjection
from dsh.core.session import Session, SessionHeader, SessionStore, canonical_header, header_equals
from dsh.core.tool_calls import execute_tool_calls
from dsh.core.agent_loop_settings import (
    AGENT_LOOP_CONFIG_SCHEMA, AGENT_LOOP_SETTINGS_NAMESPACE, AGENT_LOOP_SETTINGS_SCHEMA,
    DEFAULT_MAX_PARALLEL_TOOL_CALLS, install_parallel_settings,
)
from dsh.core.tools import ToolsService
from dsh.core.agent_factory import FactoryTransaction
from dsh.core.abort import AbortController
from dsh.core.session.preparation import SessionPreparation
from dsh.core.configured_agents import ConfiguredStartup, configured_agents, CONFIGURED_AGENT_IDENTITIES_KEY
from dsh.llm.error import error_chain
from dsh.llm.llm_service import LlmError


def request_proposal(header: Dict[str, Any]) -> Dict[str, Any]:
    """Remove adapter-derived values before plugins propose the next request config."""
    config = dict(header.get("config", {}))
    adapter_defaults = header.get("adapterDefaults", {})
    if adapter_defaults.get("reasoningEffort") is True:
        config.pop("reasoningEffort", None)
    if adapter_defaults.get("maxTokens") is True:
        config.pop("maxTokens", None)
    return config


from dsh.llm.stream_bridge import iter_chunks as _async_iter_chunks


class PartialBlock:
    def __init__(self, block_type: str):
        self.block_type = block_type
        self.text: str = ""
        self.tool_call_id: Optional[str] = None
        self.tool_call_name: Optional[str] = None
        self.tool_call_arguments: str = ""
        self.block: Optional[Dict[str, Any]] = None  # frozen by block-end


class BlockAssembler:
    """
    Incremental chunk-to-message assembler.
    1:1 with reference `packages/llm/llm/src/assembler.ts`.
    """

    def __init__(self):
        self._partials: Dict[int, PartialBlock] = {}
        self._order: List[int] = []
        self._usage: Optional[Dict[str, Any]] = None
        self._finish: Optional[Dict[str, Any]] = None
        self._replayState: Optional[Dict[str, Any]] = None
        # legacy aliases for existing call sites
        self.timing: Optional[Dict[str, Any]] = None
        self.failure: Optional[Dict[str, Any]] = None

    @property
    def usage(self) -> Optional[Dict[str, Any]]:
        return self._usage

    @usage.setter
    def usage(self, v: Optional[Dict[str, Any]]) -> None:
        self._usage = v

    @property
    def finish(self) -> Dict[str, Any]:
        return self._finish if self._finish is not None else {"kind": "stop"}

    @property
    def replayState(self) -> Optional[Dict[str, Any]]:
        return self._replayState

    @property
    def finish_kind(self) -> str:
        k = self.finish.get("kind")
        return k if isinstance(k, str) else "stop"

    @finish_kind.setter
    def finish_kind(self, v: str) -> None:
        # map legacy string to finish object
        if v == "max-tokens":
            self._finish = {"kind": "max-tokens"}
        elif v == "completed":
            self._finish = {"kind": "stop"}
        else:
            self._finish = {"kind": v}

    def _ensure(self, index: int, block_type: str) -> PartialBlock:
        p = self._partials.get(index)
        if p is None:
            p = PartialBlock(block_type=block_type)
            self._partials[index] = p
            self._order.append(index)
        return p

    def _mustGet(self, index: int) -> PartialBlock:
        p = self._partials.get(index)
        if p is None:
            raise RuntimeError(f"BlockAssembler invariant violated: no partial for index {index}")
        return p

    def push(self, chunk: Any) -> None:
        # 1:1 with TS push switch
        if isinstance(chunk, str):
            if chunk:
                partial = self._ensure(0, "text")
                if partial.block is not None:
                    return
                partial.text += chunk
            return
        if not isinstance(chunk, dict):
            return
        ctype = chunk.get("type")
        if ctype == "block-start":
            idx = chunk.get("index", 0)
            btype = chunk.get("blockType", "text")
            if idx not in self._partials:
                self._order.append(idx)
                self._partials[idx] = PartialBlock(block_type=btype)
                self._partials[idx].block_type = btype
                self._partials[idx].text = ""
                self._partials[idx].tool_call_arguments = ""
            return
        if ctype in ("text-delta", "reasoning-delta"):
            idx = chunk.get("index", 0 if ctype == "text-delta" else 1)
            btype = "text" if ctype == "text-delta" else "reasoning"
            partial = self._ensure(idx, btype)
            if partial.block is not None:
                return
            partial.text += chunk.get("text", "")
            return
        if ctype == "tool-call-delta":
            idx = chunk.get("index", 10)
            partial = self._ensure(idx, "tool-call")
            if partial.block is not None:
                return
            if chunk.get("id"):
                partial.tool_call_id = chunk["id"]
            if chunk.get("name"):
                partial.tool_call_name = chunk["name"]
            if chunk.get("argumentsDelta"):
                partial.tool_call_arguments += chunk["argumentsDelta"]
            return
        if ctype == "block-end":
            idx = chunk.get("index", 0)
            block = chunk.get("block", {})
            btype = block.get("type", "text") if isinstance(block, dict) else "text"
            partial = self._ensure(idx, btype)
            if partial.block is not None:
                return
            partial.block = dict(block) if isinstance(block, dict) else {"type": btype}
            # keep text/tool fields in sync for legacy callers (optional)
            if btype in ("text", "reasoning") and isinstance(block, dict) and "text" in block:
                partial.text = block["text"]
            elif btype == "tool-call" and isinstance(block, dict):
                if block.get("id"):
                    partial.tool_call_id = block["id"]
                if block.get("name"):
                    partial.tool_call_name = block["name"]
                if block.get("arguments") is not None:
                    args = block["arguments"]
                    partial.tool_call_arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            return
        if ctype == "usage":
            if "usage" in chunk and isinstance(chunk["usage"], dict):
                self._usage = chunk["usage"]
            return
        if ctype == "finish":
            reason = chunk.get("reason")
            if isinstance(reason, dict) and "kind" in reason:
                self._finish = dict(reason)
            elif isinstance(reason, str):
                self._finish = {"kind": reason}
            else:
                self._finish = {"kind": "stop"}
            if "replayState" in chunk:
                self._replayState = chunk["replayState"]
            if "failure" in chunk and isinstance(chunk["failure"], dict):
                self.failure = chunk["failure"]
            return
        # fallback for raw provider deltas (non-StreamChunk) - best-effort, with freeze
        if "message" in chunk and isinstance(chunk["message"], dict):
            msg = chunk["message"]
            content = msg.get("content")
            if content and isinstance(content, str):
                partial = self._ensure(0, "text")
                if partial.block is None and not partial.text:
                    partial.text = content
            tcalls = msg.get("tool_calls")
            if tcalls and isinstance(tcalls, list):
                for idx, tc in enumerate(tcalls):
                    partial = self._ensure(100 + idx, "tool-call")
                    if partial.block is not None:
                        continue
                    cid = tc.get("id") or str(tc.get("index", idx))
                    func = tc.get("function", {}) if "function" in tc else tc
                    name = func.get("name", "")
                    args = func.get("arguments", "")
                    partial.tool_call_id = cid
                    partial.tool_call_name = name
                    partial.tool_call_arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        if "usage" in chunk and isinstance(chunk["usage"], dict):
            self._usage = chunk["usage"]
        if "timing" in chunk and isinstance(chunk["timing"], dict):
            self.timing = chunk["timing"]
        finish_reason = chunk.get("finish_reason") or chunk.get("reason")
        if isinstance(finish_reason, dict):
            finish_reason = finish_reason.get("kind") or finish_reason.get("type")
        if finish_reason == "length" or finish_reason == "max_tokens" or finish_reason == "max-tokens":
            self._finish = {"kind": "max-tokens"}
        # raw openai delta fallback (with freeze) - 1:1 with extra tolerance
        delta = chunk.get("delta")
        if delta is None and isinstance(chunk.get("choices"), list) and chunk.get("choices"):
            try:
                delta = chunk["choices"][0].get("delta")
            except Exception:
                delta = None
        if isinstance(delta, dict):
            text_delta = delta.get("content") or delta.get("text")
            if text_delta and isinstance(text_delta, str):
                partial = self._ensure(0, "text")
                if partial.block is None:
                    partial.text += text_delta
            reasoning_delta = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning_delta and isinstance(reasoning_delta, str):
                partial = self._ensure(1, "reasoning")
                if partial.block is None:
                    partial.text += reasoning_delta
            tool_calls = delta.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    tc_idx = tc.get("index", 0) + 10
                    partial = self._ensure(tc_idx, "tool-call")
                    if partial.block is not None:
                        continue
                    cid = tc.get("id")
                    if cid:
                        partial.tool_call_id = cid
                    func = tc.get("function", {}) if "function" in tc else tc
                    name = func.get("name")
                    if name:
                        partial.tool_call_name = name
                    args_delta = func.get("arguments") or tc.get("arguments", "")
                    if args_delta and isinstance(args_delta, str):
                        partial.tool_call_arguments += args_delta

    def _assemble(self, partial: PartialBlock, index: int) -> Dict[str, Any]:
        if partial.block is not None:
            return dict(partial.block)
        if partial.block_type == "text":
            return {"type": "text", "text": partial.text}
        if partial.block_type == "reasoning":
            return {"type": "reasoning", "text": partial.text}
        if partial.block_type == "tool-call":
            return {
                "type": "tool-call",
                "id": partial.tool_call_id or f"call-{index}",
                "name": partial.tool_call_name or "",
                "arguments": partial.tool_call_arguments,
            }
        raise RuntimeError(f'cannot assemble incomplete block of type "{partial.block_type}"')

    def _assembled(self) -> Dict[str, Any]:
        all_blocks = [self._assemble(self._mustGet(idx), idx) for idx in self._order]
        kept = None
        if self.finish.get("kind") == "max-tokens":
            kept = [b.get("type") != "tool-call" for b in all_blocks]
        blocks = all_blocks if kept is None else [b for b, k in zip(all_blocks, kept) if k]
        envelope = self._replayState
        if envelope is None or envelope.get("blocks") is None:
            return {"blocks": blocks, "replay": envelope}
        if len(envelope.get("blocks", [])) != len(all_blocks):
            return {"blocks": blocks, "replay": None}
        if kept is None or len(blocks) == len(all_blocks):
            return {"blocks": blocks, "replay": envelope}
        filtered = [b for b, k in zip(envelope["blocks"], kept) if k]
        return {"blocks": blocks, "replay": {"response": envelope.get("response"), "blocks": filtered}}

    def blocks(self) -> List[Dict[str, Any]]:
        return self._assembled()["blocks"]

    def interruptedBlocks(self) -> List[Dict[str, Any]]:
        # alias for camelCase
        return self.interrupted_blocks()

    def interrupted_blocks(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for idx in self._order:
            partial = self._mustGet(idx)
            btype = partial.block.get("type") if partial.block else partial.block_type
            if btype not in ("text", "reasoning"):
                continue
            block = self._assemble(partial, idx)
            if block.get("text", "").strip() == "":
                continue
            result.append(block)
        return result

    def message(self, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        src = source if isinstance(source, dict) else {"kind": "plugin", "plugin": "dsh-llm/assembler"}
        return {"role": "assistant", "content": self.blocks(), "source": src}



def _invoke_llm_callable(
    fn: Callable[..., Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    system: Optional[str] = None,
    request: Optional[Dict[str, Any]] = None,
) -> Any:
    import inspect
    sig = None
    try:
        sig = inspect.signature(fn)
    except Exception:
        pass

    req_dict = dict(request) if request is not None else {}
    req_dict["messages"] = messages
    if tools is not None:
        req_dict["tools"] = tools
    if system is not None:
        req_dict["system"] = system

    if sig is not None:
        params = list(sig.parameters.values())
        call_inputs = dict(req_dict)
        for canonical_name, legacy_name in (("maxTokens", "max_tokens"), ("reasoningEffort", "reasoning_effort")):
            if legacy_name in sig.parameters and canonical_name in call_inputs:
                call_inputs.setdefault(legacy_name, call_inputs[canonical_name])
        if len(params) == 1 and params[0].name in ("request", "req", "call_request"):
            return fn(req_dict)
        if "request" in sig.parameters:
            return fn(req_dict)
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if "messages" in sig.parameters:
            call_kwargs = call_inputs if has_varkw else {k: v for k, v in call_inputs.items() if k in sig.parameters}
            if "system" not in sig.parameters and system:
                msg_list = list(call_kwargs.get("messages", []))
                if not any(isinstance(m, dict) and m.get("role") == "system" for m in msg_list):
                    call_kwargs["messages"] = [{"role": "system", "content": system}] + msg_list
            return fn(**call_kwargs)
        if len(params) == 1 and params[0].kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            return fn(req_dict)
        call_kwargs = call_inputs if has_varkw else {k: v for k, v in call_inputs.items() if k in sig.parameters}
        return fn(**call_kwargs)
    else:
        try:
            return fn(req_dict)
        except TypeError:
            try:
                return fn(messages=messages, tools=tools, system=system)
            except TypeError:
                llm_messages = list(messages)
                if system and not any(isinstance(m, dict) and m.get("role") == "system" for m in llm_messages):
                    llm_messages = [{"role": "system", "content": system}] + llm_messages
                return fn(messages=llm_messages, tools=tools)


class AgentLoopService:
    """
    Concrete Agent Factory and Asynchronous Driver Service mounted at `ctx.agent_loop`.
    """

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        self.ctx = ctx
        self._config = dict(config or {})
        self._config.setdefault('agents', [])
        install_parallel_settings(ctx, self, self._config)
        self._turn_counters: Dict[str, int] = {}
        self._active_tasks: List[asyncio.Task] = []
        self._factory_abort = AbortController()
        self._accepting = True
        self._transactions = set()
        self._wrappers = set()
        self._configured = ConfiguredStartup(self)
        self._default_agent: Optional[Agent] = None
        self._request_header_logged: Dict[str, bool] = {}

    @property
    def config(self) -> Dict[str, Any]:
        return dict(self._config, maxParallelToolCalls=self._parallel_settings_source()['maxParallelToolCalls'])

    def _get_turn_number(self, agent: Agent) -> int:
        session = agent.session
        last_turn = 0
        for ev in reversed(session.events):
            if isinstance(ev, dict) and ev.get("type") == "turn/start":
                last_turn = ev.get("data", {}).get("turn", 0)
                break
        return last_turn + 1

    async def _publish_preparation(self, tx, preparation, options, setup, source):
        session = preparation.session
        tx.assert_live()
        tx.scope = create_scope(self.ctx, ScopeKey({"sessionId": session.id}))
        # This port uses scoped Contexts as agent event carriers. Preserve the
        # routing predicate as well as the key, so sibling listeners do not
        # receive each other's agent/tool events.
        tx.scope.ctx._filter_hook = scope_target(tx.scope.ctx, scope_of(tx.scope.ctx))
        tx.agent = Agent(session=session, options=options, ctx=tx.scope.ctx)
        tx.agent.ctx = tx.scope.ctx.extend({"agent": tx.agent})
        tx.agent.ctx._filter_hook = scope_target(tx.agent.ctx, scope_of(tx.agent.ctx))
        if setup is not None:
            result = await tx.race(lambda: setup(tx.agent.ctx))
            commit = getattr(result, 'commit', None)
            if callable(commit):
                await tx.race(commit)
        tx.assert_live()
        sessions = tx.agent.ctx.get('sessions')
        agents = self.ctx.get('agents')
        tx.detach_session = sessions.enter(session)
        cursor, owner_agent = tx.owner, None
        while cursor is not None:
            if 'agent' in cursor.__dict__:
                owner_agent = cursor.__dict__['agent']
                break
            cursor = cursor.__dict__.get('_parent')
        tx.detach_agent = agents.enter(tx.agent, owner=owner_agent)
        sessions.announce(session)
        tx.assert_live()
        agents.announce(tx.agent)
        tx.assert_live()
        tx.agent.ctx.emit('agent/session-start', {'agent': tx.agent, 'source': source})
        tx.assert_live()
        tx.driver = asyncio.create_task(self._drive_agent(tx.agent))
        self._active_tasks.append(tx.driver)
        tx.agent._driver_task = tx.driver
        return AgentHandle(agent=tx.agent, disposer=tx.dispose)

    @staticmethod
    def _validate_options(options):
        max_t = getattr(options, 'max_tokens', None)
        if max_t is not None and (not isinstance(max_t, int) or isinstance(max_t, bool)
                                  or max_t <= 0 or max_t > 9007199254740991):
            raise ValueError('agent maxTokens must be a positive safe integer')

    async def create_agent(self, session_id=None, options=None, meta=None, setup=None,
                           seed=None, signal=None, owner_ctx=None):
        self._validate_options(options)
        sid = session_id if session_id is not None else 'session-' + uuid.uuid4().hex[:8]
        tx = FactoryTransaction(self, owner_ctx or self.ctx, sid, signal)
        wrapper = asyncio.get_running_loop().create_future()
        self._wrappers.add(wrapper)
        preparation = None
        try:
            preparation = SessionPreparation.create(self.ctx.get('sessions').prepare(sid, seed=seed, meta=meta))
            return await self._publish_preparation(tx, preparation, options, setup, 'startup')
        except BaseException:
            await tx.dispose()
            raise
        finally:
            try:
                if preparation is not None:
                    preparation.dispose()
            finally:
                self._wrappers.discard(wrapper)
                if not wrapper.done():
                    wrapper.set_result(None)

    create = create_agent

    async def resume(self, resume_session_id, options=None, setup=None, signal=None, owner_ctx=None, persistence=None):
        self._validate_options(options)
        sid = resume_session_id
        if self.ctx.get('sessions').get(sid) is not None or self.ctx.get('agents').get(sid) is not None:
            raise RuntimeError('cannot resume session "%s" while it is live' % sid)
        if persistence is None:
            persistence = self.ctx.get('sessionPersistence') or self.ctx.get('session_persistence')
        if persistence is None:
            raise RuntimeError('no session_persistence service configured for resume')
        tx = FactoryTransaction(self, owner_ctx or self.ctx, sid, signal)
        wrapper = asyncio.get_running_loop().create_future()
        self._wrappers.add(wrapper)
        preparation = None
        async def prepare():
            method = getattr(persistence, 'prepare', None)
            if callable(method):
                result = method(sid, tx.controller.signal)
                if inspect.isawaitable(result):
                    result = await result
                return SessionPreparation.create(result)
            # Old third-party persistence implementations still expose load.
            # Their snapshot is wrapped once at this boundary, never published early.
            inspection = await persistence.load(sid)
            return SessionPreparation.create(self.ctx.get('sessions').prepare(
                sid, seed=inspection.events, meta=inspection.meta, seedSource='persistence'))
        try:
            preparation = await tx.race(prepare, lambda late: late.dispose())
            return await self._publish_preparation(tx, preparation, options, setup, 'resume')
        except BaseException:
            await tx.dispose()
            raise
        finally:
            try:
                if preparation is not None:
                    preparation.dispose()
            finally:
                self._wrappers.discard(wrapper)
                if not wrapper.done():
                    wrapper.set_result(None)

    async def _drive_agent(self, agent: Agent) -> None:
        """Background driver loop pumping the agent's inbox."""
        try:
            while True:
                await agent._wake_event.wait()
                agent._wake_event.clear()

                if agent.inbox.is_empty() and not agent.is_cancelled():
                    agent.set_phase("idle")
                    continue

                agent.set_phase("running")

                agents_svc: Optional[AgentRegistry] = self.ctx.get("agents")
                if agents_svc:
                    await agents_svc.with_initiator_async(agent, self._kick(agent))
                else:
                    await self._kick(agent)

                agent.set_phase("idle")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if hasattr(self.ctx, "logger"):
                try:
                    self.ctx.logger("agent_loop").error("agent driver crashed: %s", str(e))
                except Exception:
                    pass
        finally:
            agent.set_phase("idle")

    async def _kick(self, agent: Agent) -> None:
        try:
            while await self._turn(agent):
                pass
        except Exception:
            pass
        finally:
            agent.set_status("idle")

    async def _turn(self, agent: Agent) -> bool:
        session = agent.session
        turn_num = self._get_turn_number(agent)
        setattr(agent, "_last_turn", turn_num)
        session.append("turn/start", {"turn": turn_num})

        turn_ends: Optional[Dict[str, Any]] = None
        target = "next-turn"
        step_num = 0

        runtime_context_proj = RuntimeContextProjection(agent.ctx, session)

        try:
            while True:
                if agent.is_cancelled():
                    cause = agent.take_cancel_cause()
                    turn_ends = {"kind": "aborted", "reason": cause}
                    break

                step_num += 1

                claimed = agent.inbox.claim(target=target, turn=turn_num)
                decision_messages = list(claimed)

                sp_svc = self.ctx.get("systemPrompt") or self.ctx.get("system_prompt")
                if sp_svc and hasattr(sp_svc, "assemble"):
                    from dsh.core.system_prompt import render_prompt, render_context_sections, join_context_sections
                    assembly = await await_callback_result(sp_svc.assemble({
                        "agent": agent,
                        "session": session,
                        "scope": scope_of(agent.ctx),
                    }))
                    system_prompt = render_prompt(assembly)
                    context_sections = render_context_sections(assembly)
                    candidate_ctx = runtime_context_proj.project(join_context_sections(context_sections), context_sections)
                    if candidate_ctx:
                        decision_messages.append(candidate_ctx)
                else:
                    system_prompt = "You are a helpful software engineer assistant."
                    persona = self.ctx.get("persona")
                    if persona and hasattr(persona, "get_prompt"):
                        system_prompt = persona.get_prompt()

                    system_prompt = await self.ctx.waterfall("system-prompt/assemble", system_prompt)
                    system_prompt = await self.ctx.waterfall("agent/prompt-assemble", system_prompt)

                    runtime_ctx_text = await self.ctx.waterfall("agent/runtime-context", "")
                    if runtime_ctx_text:
                        candidate_ctx = runtime_context_proj.project(runtime_ctx_text, [])
                        if candidate_ctx:
                            decision_messages.append(candidate_ctx)

                request_payload = {
                    "agent": agent,
                    "messages": claimed,
                    "turn": turn_num,
                    "step": step_num,
                }
                request_payload['signal'] = getattr(agent, '_cancel_event', None)
                pre_step_res = await agent.ctx.waterfall("agent/pre-step", request_payload,
                    lambda *_: {'kind': 'accept', 'messages': decision_messages})

                starts_series = False
                if isinstance(pre_step_res, dict):
                    if pre_step_res.get("kind") == "reject":
                        turn_ends = {"kind": "blocked"}
                        return False
                    if "messages" in pre_step_res and isinstance(pre_step_res["messages"], list):
                        decision_messages = pre_step_res["messages"]
                    if pre_step_res.get("startsRequestSeries") or pre_step_res.get("starts_request_series") or pre_step_res.get("startsSeries"):
                        starts_series = True

                if turn_ends and len(decision_messages) == 0:
                    break

                if step_num == 1 and len(decision_messages) == 0 and len(session.surface.nodes) == 0:
                    turn_ends = {"kind": "completed"}
                    return False

                session.append("step/start", {"turn": turn_num, "step": step_num})

                try:
                    for msg in decision_messages:
                        if isinstance(msg, dict) and "id" in msg and "role" in msg and "source" in msg:
                            session.append("user/message", msg, surface_op="append")
                        elif isinstance(msg, dict):
                            session.append_user_message(
                                msg.get("content", ""),
                                source=msg.get("source"),
                                message_id=msg.get("id"),
                            )
                        else:
                            session.append_user_message(str(msg))

                    tools_to_pass = assembly.get("tools") if ("assembly" in locals() and isinstance(assembly, dict) and bool(assembly.get("tools"))) else None
                    step_end = await self._step(agent, turn_num, step_num, system_prompt, starts_series=starts_series, tool_schemas=tools_to_pass)
                    if agent.is_cancelled():
                        cause = agent.take_cancel_cause()
                        turn_ends = {"kind": "aborted", "reason": cause}
                        break
                    if step_end:
                        if turn_ends is None or turn_ends.get("kind") != "max-tokens":
                            turn_ends = step_end
                finally:
                    session.append("step/end", {"turn": turn_num, "step": step_num})

                if turn_ends and len(agent.inbox.next_step) == 0:
                    await agent.ctx.serial("agent/turn-stopping", {"turn": turn_num, "agent": agent})

                if turn_ends and len(agent.inbox.next_step) == 0:
                    break
                elif turn_ends and len(agent.inbox.next_step) > 0:
                    turn_ends = None

                target = "next-step"

        except Exception as e:
            if agent.is_cancelled():
                turn_ends = {"kind": "aborted", "reason": agent.take_cancel_cause()}
                raise
            turn_ends = {"kind": "error", "error": dict(e.failure) if isinstance(e, LlmError)
                         else {"message": error_chain(e), "code": "UNKNOWN"}}
            raise
        except asyncio.CancelledError:
            cause = agent.take_cancel_cause() or {"kind": "user"}
            turn_ends = {"kind": "aborted", "reason": cause}
        finally:
            final_reason = turn_ends or {"kind": "completed"}
            session.append("turn/end", {"turn": turn_num, "reason": final_reason})
            self.ctx.emit("agent/turn-stopped", {"agent": agent, "turn": turn_num, "session": session})

        if turn_ends and turn_ends.get("kind") == "aborted":
            return False
        pending = agent.inbox.has_pending
        if pending:
            agent.reset_cancel_signal()
        return pending

    async def _step(self, agent, turn, step, system_prompt, starts_series=False, tool_schemas=None):
        while True:
            result = await self._step_once(agent, turn, step, system_prompt, starts_series, tool_schemas)
            if result != {"kind": "retry"}:
                return result
            if agent.is_cancelled():
                raise asyncio.CancelledError()
            starts_series = False

    async def _step_once(
        self,
        agent: Agent,
        turn: int,
        step: int,
        system_prompt: str,
        starts_series: bool = False,
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        session = agent.session
        llm_service = self.ctx.get("llm")
        if tool_schemas is None:
            tools_service = self.ctx.get("tools")
            tool_schemas = tools_service.schemas(scope_of(agent.ctx)) if (tools_service and hasattr(tools_service, "schemas")) else (tools_service.get_schemas() if tools_service else [])

        raw_provider = agent.options.provider or getattr(llm_service, "provider", "openai")
        raw_model = agent.options.model or getattr(llm_service, "model", "deepseek-chat")
        provider_name = str(raw_provider) if raw_provider is not None else "openai"
        model_name = str(raw_model) if raw_model is not None else "deepseek-chat"

        persisted_header = session.request_header()
        persisted_config = persisted_header.get("config", {}) if persisted_header else {}
        logged_before = self._request_header_logged.get(agent.id, False)

        seed_config = (
            request_proposal(persisted_header)
            if logged_before and persisted_header
            else {
                "provider": provider_name,
                "model": model_name,
                **({"maxTokens": agent.options.max_tokens} if agent.options.max_tokens is not None else {}),
                **({"reasoningEffort": agent.options.reasoning_effort} if agent.options.reasoning_effort is not None else {}),
            }
        )

        request_context = dict(seed_config)
        request_context.update(agent=agent, turn=turn, step=step, signal=getattr(agent, "signal", None))
        proposed_config = await agent.ctx.waterfall(
            "agent/request", request_context, lambda *_args: dict(seed_config))
        if agent.is_cancelled():
            raise asyncio.CancelledError()
        config_fields = ("provider", "model", "reasoningEffort", "maxTokens", "temperature", "stop")
        effective_config = {key: value for key, value in (proposed_config or seed_config).items()
                            if key in config_fields}
        if isinstance(proposed_config, dict):
            provider_name = str(proposed_config.get("provider", provider_name))
            model_name = str(proposed_config.get("model", model_name))

        public_prepare = getattr(llm_service, "prepareCall", None) if getattr(llm_service, "ctx", None) is not None else None
        canonical_prepared = callable(public_prepare)
        prepare = public_prepare if canonical_prepared else getattr(llm_service, "prepare_call", None)
        prepared_adapter = None
        if callable(prepare):
            try:
                prepared_adapter = await prepare(effective_config, agent.signal)
            except LlmError as error:
                if not canonical_prepared or error.code != 'NO_ADAPTER':
                    raise
            if prepared_adapter is not None:
                if canonical_prepared:
                    effective_config = dict(prepared_adapter['config'])
                    provider_name, model_name = effective_config['provider'], effective_config['model']
                else:
                    for field in ('maxTokens', 'reasoningEffort'):
                        if prepared_adapter.get(field) is not None:
                            effective_config[field] = prepared_adapter[field]
        if agent.is_cancelled():
            raise asyncio.CancelledError()

        header_data = canonical_header({
            "system": system_prompt,
            "tools": tool_schemas,
            "config": dict(effective_config, provider=provider_name, model=model_name),
            **({'adapterDefaults': prepared_adapter['adapterDefaults']} if prepared_adapter is not None else {}),
        })

        # Projection dict subclasses must cross the durable-log boundary as plain JSON.
        header_data = json.loads(json.dumps(header_data, ensure_ascii=False))
        surface_gen = session.surface.replace_generation
        last_gen = getattr(agent, "_last_surface_gen", None)
        surface_changed = (last_gen is not None and last_gen != surface_gen)
        effective_starts_series = starts_series or surface_changed
        setattr(agent, "_last_surface_gen", surface_gen)

        baseline_header = session.request_header()
        if not logged_before:
            reason = "initial" if baseline_header is None else "resume"
            session.append_request_header(header_data, reason=reason)
            self._request_header_logged[agent.id] = True
        elif baseline_header is None or not header_equals(baseline_header, header_data):
            session.append_request_header(header_data, reason="change", starts_series=effective_starts_series if effective_starts_series else None)
        elif effective_starts_series:
            session.append_request_header(header_data, reason="series")

        baseline_ctx = session.request_context()
        model_context = prepared_adapter.get('context') if prepared_adapter is not None else None
        context_window = model_context.get('contextWindow') if isinstance(model_context, dict) else None
        if (
            baseline_ctx is None
            or baseline_ctx.get("provider") != provider_name
            or baseline_ctx.get("model") != model_name
            or baseline_ctx.get('contextWindow') != context_window
        ):
            session.append_request_context(provider=provider_name, model=model_name, context_window=context_window)

        messages = session.derive_messages()

        if not llm_service:
            raise RuntimeError("LLM service ('ctx.llm') is missing")

        assembler = BlockAssembler()
        chunk_seqs: List[int] = []
        retry_policy = (llm_service.retry_policy(provider_name)
                        if callable(getattr(llm_service, "retry_policy", None)) else None)
        if prepared_adapter is not None:
            retry_policy = prepared_adapter.get("retryPolicy")

        request_obj = {
            **header_data['config'],
            "sessionId": session.id,
            "messages": messages,
            "provider": provider_name,
            "model": model_name,
            **({"tools": tool_schemas} if tool_schemas else {}),
            **({"system": system_prompt} if system_prompt else {}),
            **({"maxTokens": agent.options.max_tokens} if not canonical_prepared and getattr(agent.options, "max_tokens", None) is not None else {}),
            **({"reasoningEffort": agent.options.reasoning_effort} if not canonical_prepared and getattr(agent.options, "reasoning_effort", None) is not None else {}),
            **({'signal': agent.signal} if canonical_prepared else {}),
        }

        from dsh.llm.agent_request import mark_agent_loop_request
        request_obj = mark_agent_loop_request(request_obj)

        async def recover_request(failure):
            recovery = await agent.ctx.waterfall(
                "agent/request-error",
                {"agent": agent, "error": failure["message"], "failure": failure,
                 "provider": provider_name, "turn": turn, "step": step,
                 "retryPolicy": retry_policy, "signal": getattr(agent, "_cancel_event", None)},
            )
            if agent.is_cancelled():
                raise asyncio.CancelledError()
            return isinstance(recovery, dict) and recovery.get("kind") == "retry"

        try:
            stream_fn = getattr(llm_service, "stream", None) if canonical_prepared else (
                getattr(llm_service, "chat_completion_stream", None) or getattr(llm_service, "stream", None))
            used_stream = False
            if stream_fn and callable(stream_fn):
                try:
                    def open_stream(*_args):
                        if prepared_adapter is not None and 'stream' in prepared_adapter:
                            if canonical_prepared:
                                return prepared_adapter['stream'](request_obj)
                            return prepared_adapter["stream"](dict(request_obj, signal=getattr(agent, "_cancel_event", None)))
                        if canonical_prepared:
                            return stream_fn(request_obj)
                        return _invoke_llm_callable(
                            stream_fn, messages=request_obj["messages"],
                            tools=request_obj.get("tools"), system=request_obj.get("system"),
                            request=request_obj)

                    stream_iter = open_stream() if canonical_prepared else await self.ctx.waterfall("llm/stream", request_obj, open_stream)
                    reader = _async_iter_chunks(stream_iter, cancel_check=agent.is_cancelled)
                    try:
                        async for chunk in reader:
                            # TS port yields StreamChunk dict; legacy tuple (ev_type, ev_payload) also supported
                            if isinstance(chunk, (list, tuple)) and len(chunk) == 2:
                                ev_type, ev_payload = chunk
                                if ev_type == "chunk":
                                    ev_payload = ev_payload
                                elif ev_type == "finish":
                                    assembler.push(ev_payload)
                                    used_stream = True
                                    continue
                                else:
                                    ev_payload = chunk
                            else:
                                ev_payload = chunk
                            # Treat every StreamChunk dict as a chunk
                            if not isinstance(ev_payload, dict):
                                continue
                            chunk_payload = {
                                "turn": turn,
                                "step": step,
                                "chunk": ev_payload,
                                **(ev_payload if isinstance(chunk, (list, tuple)) else {}),
                            }
                            chunk_ev = session.append(
                                "assistant/chunk",
                                chunk_payload,
                                ignorable=True,
                            )
                            seq = chunk_ev.get("seq", 0) if isinstance(chunk_ev, dict) else getattr(chunk_ev, "seq", 0)
                            chunk_seqs.append(seq)
                            assembler.push(ev_payload)
                            self.ctx.emit("session/chunk", session, chunk_ev)
                            self.ctx.emit("assistant/chunk", chunk_ev)
                            if ev_payload.get("type") == "finish":
                                used_stream = True
                    finally:
                        await reader.aclose()
                    if chunk_seqs or assembler._order:
                        used_stream = True
                except asyncio.CancelledError:
                    content = assembler.interrupted_blocks()
                    if content:
                        session.append_assistant_message(
                            {"content": content, "role": "assistant", **({"source": {
                                "kind": "model", "provider": request_obj['provider'], "model": request_obj['model']
                            }} if canonical_prepared else {})},
                            turn=turn,
                            step=step,
                            usage=assembler.usage if canonical_prepared else None,
                            interrupted=canonical_prepared,
                            surface_op="append",
                            source_event_seqs=chunk_seqs if chunk_seqs else None,
                        )
                    raise
                except Exception as e:
                    # If partial chunks were already emitted before failure, preserve them
                    if assembler._order and (not canonical_prepared or agent.is_cancelled()):
                        content = assembler.interrupted_blocks()
                        if content:
                            session.append_assistant_message(
                                {"content": content, "role": "assistant", **({"source": {
                                    "kind": "model", "provider": request_obj['provider'], "model": request_obj['model']
                                }} if canonical_prepared else {})},
                                turn=turn,
                                step=step,
                                usage=assembler.usage if canonical_prepared else None,
                                interrupted=canonical_prepared,
                                surface_op="append",
                                source_event_seqs=chunk_seqs if chunk_seqs else None,
                            )
                    raise

            if not used_stream:
                sync_fn = getattr(llm_service, "chat_completion", None)
                sync_res = _invoke_llm_callable(
                    sync_fn,
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                    system=system_prompt if system_prompt else None,
                ) if sync_fn and callable(sync_fn) else None
                if isinstance(sync_res, dict):
                    content = sync_res.get("content", "")
                    tcalls = sync_res.get("tool_calls", [])
                    msg_blocks = []
                    if content:
                        msg_blocks.append({"type": "text", "text": content})
                    if tcalls:
                        for tc in tcalls:
                            func = tc.get("function", {}) if "function" in tc else tc
                            msg_blocks.append({
                                "type": "tool-call",
                                "id": tc.get("id", ""),
                                "name": func.get("name", ""),
                                "arguments": func.get("arguments", "{}"),
                            })
                    assembler._partials[0] = PartialBlock("text")
                    assembler._partials[0].text = content if isinstance(content, str) else ""
                    assembler._order = [0]
                    if tcalls:
                        for idx, tc in enumerate(tcalls):
                            p = PartialBlock("tool-call")
                            p.tool_call_id = tc.get("id", "")
                            func = tc.get("function", {}) if "function" in tc else tc
                            p.tool_call_name = func.get("name", "")
                            p.tool_call_arguments = func.get("arguments", "{}")
                            assembler._partials[10 + idx] = p
                            assembler._order.append(10 + idx)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            failure_payload = dict(getattr(e, "failure", None) or {
                "message": error_chain(e),
                "code": getattr(e, "code", "UNKNOWN"),
            })
            if await recover_request(failure_payload):
                return {"kind": "retry"}
            raise

        if assembler.finish_kind in ("error", "aborted"):
            failure = assembler.finish["failure"]
            if await recover_request(failure):
                return {"kind": "retry"}
            error = LlmError(failure["message"], failure["code"])
            error.failure = dict(failure)
            raise error

        blocks = assembler.blocks()
        source = {
            "kind": "model",
            "provider": provider_name,
            "model": model_name,
            **({"replayState": assembler.replayState} if assembler.replayState is not None else {}),
        }
        assistant_msg = {
            "role": "assistant",
            "content": blocks if canonical_prepared or blocks else [{"type": "text", "text": ""}],
            "source": source,
        }
        tool_calls = [b for b in blocks if b.get("type") == "tool-call"]

        session.append_assistant_message(
            assistant_msg,
            turn=turn,
            step=step,
            usage=assembler.usage,
            timing=assembler.timing,
            surface_op="append",
            source_event_seqs=chunk_seqs if chunk_seqs else None,
        )

        if assembler.finish_kind == "max-tokens":
            return {"kind": "max-tokens"}

        if not tool_calls:
            return {"kind": "completed"}

        outcome = await execute_tool_calls(
            ctx=self.ctx,
            agent=agent,
            turn=turn,
            step=step,
            tool_calls=tool_calls,
            signal=getattr(agent, "_cancel_event", None),
            accept_context=lambda ctx_item: agent.inbox.splice("next-step", len(agent.inbox.next_step), 0, [ctx_item]),
            max_parallel=lambda: self.config['maxParallelToolCalls'],
        )

        return {"kind": "completed"} if outcome.get("concluded") else None

    async def run_turn(self, user_input: str, max_steps: int = 10) -> str:
        """Backward-compatible run_turn helper."""
        if self._default_agent is None:
            handle = await self.create_agent("default-session")
            self._default_agent = handle.agent

        agent = self._default_agent
        agent.followup(user_input)
        await agent.when_idle()

        for event in reversed(agent.session.events):
            if event.get("type") == "assistant/message":
                msg = event.get("data", {}).get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    if texts:
                        return "".join(texts)
        return ""

    async def teardown(self) -> None:
        self._accepting = False
        self._factory_abort.abort(RuntimeError('agent loop is not active'))
        await self._configured.drain()
        await asyncio.gather(*(tx.dispose() for tx in list(self._transactions)))
        wrappers = [task for task in self._wrappers if task is not asyncio.current_task()]
        if wrappers:
            await asyncio.gather(*wrappers, return_exceptions=True)



class AgentLoopPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent-loop`: Core agent loop & factory driver.
    """

    id = "agent-loop"
    name = "@deepseek-ai/dsh-agent-loop"
    Config = AGENT_LOOP_CONFIG_SCHEMA

    def apply(self, ctx: Context) -> None:
        rows = configured_agents(self.config, ctx.get(CONFIGURED_AGENT_IDENTITIES_KEY))
        if not ctx.has("tools"):
            ctx.set_service("tools", ToolsService(ctx))

        if not ctx.has("sessions"):
            store = SessionStore(ctx=ctx)
            ctx.set_service("sessions", store)

        registry = ctx.get("agents")
        if not ctx.has("agents"):
            registry = AgentRegistry(ctx=ctx)
            ctx.set_service("agents", registry)

        agent_loop = AgentLoopService(ctx, dict(self.config, agents=rows))
        ctx.set_service("agent_loop", agent_loop)
        ctx.set_service("agentLoop", agent_loop)

        def prompt_variables(runtime_ctx):
            prompt = runtime_ctx.get("systemPrompt")
            for name in ("provider", "model"):
                prompt.variable(name, lambda context, key=name: getattr(
                    getattr(context.get("agent"), "options", None), key, None))
            prompt.variable("cwd", lambda context: getattr(
                getattr(getattr(context.get("agent"), "session", None), "header", None), "cwd", None))

        ctx.inject(["systemPrompt"], prompt_variables)

        if registry is not None:
            registry.set_factory(agent_loop)

        if hasattr(ctx, "disposable"):
            ctx.disposable(agent_loop.teardown, label="agent_loop.teardown")
        elif hasattr(ctx, "effect"):
            ctx.effect(lambda: agent_loop.teardown)
        return agent_loop._configured.mount(rows)


AgentLoop = AgentLoopPlugin

