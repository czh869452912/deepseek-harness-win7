"""
Agent handle, Inbox integration, Initiator ContextVar scoping, and AgentRegistry.
1:1 aligned with official `@deepseek-ai/dsh-agent`.
"""

import asyncio
import contextvars
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.consumed_work import ConsumedWork, fold_consumed_work
from dsh.core.inbox import Inbox
from dsh.core.session import Session, SessionHeader

_CURRENT_INITIATOR: contextvars.ContextVar[Optional["Agent"]] = contextvars.ContextVar(
    "dsh_initiator_agent", default=None
)


class AgentOptions:
    """Configuration options for an Agent."""

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        max_tokens: Optional[int] = None,
        reasoningEffort: Optional[str] = None,
        maxTokens: Optional[int] = None,
    ):
        self.provider = provider
        self.model = model
        self.reasoning_effort = reasoning_effort or reasoningEffort
        self.max_tokens = max_tokens if max_tokens is not None else maxTokens

    @property
    def reasoningEffort(self) -> Optional[str]:
        return self.reasoning_effort

    @property
    def maxTokens(self) -> Optional[int]:
        return self.max_tokens

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {}
        if self.provider is not None:
            res["provider"] = self.provider
        if self.model is not None:
            res["model"] = self.model
        if self.reasoning_effort is not None:
            res["reasoningEffort"] = self.reasoning_effort
        if self.max_tokens is not None:
            res["maxTokens"] = self.max_tokens
        return res


class CancelOptions:
    """Options for canceling an Agent."""

    def __init__(self, keep_inbox: bool = False, keepInbox: Optional[bool] = None):
        self.keep_inbox = keepInbox if keepInbox is not None else keep_inbox

    @property
    def keepInbox(self) -> bool:
        return self.keep_inbox


class Agent:
    """
    Public live-agent handle.
    Provides inbox queuing (followup, steer, inject), status tracking, cancellation, and when_idle synchronization.
    """

    def __init__(
        self,
        session: Session,
        options: Optional[AgentOptions] = None,
        ctx: Optional[Context] = None,
        agent_id: Optional[str] = None,
    ):
        self._id = agent_id
        self.id = agent_id if agent_id is not None else session.id
        self.session = session
        self.options = options or AgentOptions()
        self.ctx = ctx or Context()
        self.inbox = Inbox(session=self.session, ctx=self.ctx, agent=self)
        self._status: str = "idle"
        self._phase_kind: str = "idle"  # "idle", "maintenance", "running"
        self._wake_event = asyncio.Event()
        self._cancel_event = asyncio.Event()
        self._cancel_cause: Optional[Dict[str, Any]] = None
        self._idle_futures: List[asyncio.Future] = []
        self._driver_task: Optional[asyncio.Task] = None
        self._wake_requested: bool = False

    @property
    def status(self) -> str:
        return "idle" if self._phase_kind in ("idle", "maintenance") else "running"

    def set_status(self, new_status: str) -> None:
        previous_status = self.status
        self._status = new_status
        if self._phase_kind == "running" and new_status == "idle":
            self._phase_kind = "idle"
        elif self._phase_kind == "idle" and new_status == "running":
            self._phase_kind = "running"

        current_status = self.status
        if previous_status != current_status:
            if self.ctx:
                self.ctx.emit("agent/status", {"agent": self, "status": current_status})
                self.ctx.emit("internal/status", {"agent": self, "status": current_status})
        if current_status == "idle":
            futures = list(self._idle_futures)
            self._idle_futures.clear()
            for fut in futures:
                if not fut.done():
                    fut.set_result(None)

    def set_phase(self, phase_kind: str) -> None:
        previous_status = self.status
        self._phase_kind = phase_kind
        self._status = "running" if phase_kind == "running" else "idle"
        current_status = self.status
        if previous_status != current_status:
            if self.ctx:
                self.ctx.emit("agent/status", {"agent": self, "status": current_status})
                self.ctx.emit("internal/status", {"agent": self, "status": current_status})
        if current_status == "idle":
            futures = list(self._idle_futures)
            self._idle_futures.clear()
            for fut in futures:
                if not fut.done():
                    fut.set_result(None)

    def send(self, message: Union[str, Dict[str, Any]], target: str = "next-turn", wakeup: bool = True) -> str:
        """
        Route input to inbox boundary and optionally wake driver.
        """
        msg_dict = {"role": "user", "content": message} if isinstance(message, str) else dict(message)
        waking_after_abort = wakeup and self._phase_kind != "idle" and self.is_cancelled()
        resolved_target = "next-turn" if waking_after_abort else target

        msg_id = self.inbox.append(resolved_target, msg_dict)
        if wakeup:
            if self._phase_kind != "idle":
                if self._phase_kind == "maintenance" or waking_after_abort:
                    self._wake_requested = True
            else:
                self.set_phase("running")
                self._wake_event.set()
        return msg_id

    def followup(self, message: Union[str, Dict[str, Any]]) -> str:
        """Queue a regular prompt and wake driver."""
        return self.send(message, target="next-turn", wakeup=True)

    def steer(self, message: Union[str, Dict[str, Any]]) -> str:
        """Submit mid-turn steering guidance for nearest step."""
        return self.send(message, target="next-step", wakeup=True)

    def inject(self, message: Union[str, Dict[str, Any]]) -> str:
        """Queue context without waking driver."""
        return self.send(message, target="next-step", wakeup=False)

    def cancel(
        self,
        cause: Optional[Dict[str, Any]] = None,
        keep_inbox: bool = False,
        options: Optional[CancelOptions] = None,
        reason: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Abort active driver and optionally clear inbox.
        """
        should_keep = keep_inbox or (getattr(options, "keep_inbox", False) or getattr(options, "keepInbox", False) if options else False)
        if self._phase_kind == "idle" and self.inbox.is_empty():
            if not should_keep:
                self.inbox.clear()
            return

        self._cancel_cause = cause or reason or {"kind": "user"}
        self._cancel_event.set()
        if hasattr(self, "_maintenance_abort") and self._maintenance_abort is not None:
            self._maintenance_abort.set()
        if not should_keep:
            self.inbox.clear()
            if self._phase_kind != "idle":
                self._wake_requested = False

    def is_cancelled(self) -> bool:
        return self._cancel_cause is not None

    def isCancelled(self) -> bool:
        return self.is_cancelled()

    def take_cancel_cause(self) -> Optional[Dict[str, Any]]:
        cause = self._cancel_cause
        self._cancel_cause = None
        self._cancel_event.clear()
        return cause

    def takeCancelCause(self) -> Optional[Dict[str, Any]]:
        return self.take_cancel_cause()

    async def when_idle(self) -> None:
        """Resolve when whole-agent activity reaches idle quiescence."""
        while self.status != "idle":
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._idle_futures.append(fut)
            await fut

    async def whenIdle(self) -> None:
        return await self.when_idle()

    async def run_maintenance(self, task_fn: Callable[[asyncio.Event], Any]) -> Any:
        """Run non-turn maintenance task in idle phase."""
        if self._phase_kind != "idle":
            raise RuntimeError(f'agent "{self.id}" already has active work')
        self.set_phase("maintenance")
        self._maintenance_abort = asyncio.Event()
        try:
            res = task_fn(self._maintenance_abort)
            if asyncio.iscoroutine(res):
                res = await res
            return res
        finally:
            self._maintenance_abort = None
            self._cancel_cause = None
            if self._wake_requested and self.inbox.has_pending:
                self._wake_requested = False
                self.set_phase("running")
                self._wake_event.set()
            else:
                self.set_phase("idle")

    async def runMaintenance(self, task_fn: Callable[[asyncio.Event], Any]) -> Any:
        return await self.run_maintenance(task_fn)


class AgentHandle:
    """
    Owned agent capability handle returned by AgentRegistry.create / resume.
    Proxies all Agent methods and is awaitable for backwards compatibility.
    """

    def __init__(self, agent: Agent, disposer: Callable[[], Any]):
        self.agent = agent
        self._disposer = disposer

    def __getattr__(self, name: str) -> Any:
        return getattr(self.agent, name)

    def __await__(self):
        async def _resolve():
            return self
        return _resolve().__await__()

    async def dispose(self) -> None:
        res = self._disposer()
        if asyncio.iscoroutine(res):
            await res


class _AgentEntry:
    def __init__(self, agent: Agent, owner: Optional[Agent] = None):
        self.id = agent.id
        self.agent = agent
        self.owner = owner
        self.announced = False
        self.announcing = False
        self.detach_requested = False


class AgentRegistry:
    """
    Agent Registry mounted at `ctx.agents`.
    Tracks live agents, initiator scopes, and creation factories.
    1:1 aligned with official `@deepseek-ai/dsh-agent/AgentRegistry`.
    """

    def __init__(self, ctx: Optional[Context] = None):
        self.ctx = ctx
        self._store: Dict[str, _AgentEntry] = {}
        self._factory: Optional[Any] = None
        self._initiator_state: str = "active"  # "active" | "closing" | "disposed"
        self._active_initiator_runs: int = 0
        self._initiator_drain: Optional[asyncio.Event] = None

    @property
    def initiator_state(self) -> str:
        return self._initiator_state

    @property
    def initiatorState(self) -> str:
        return self._initiator_state

    def current_initiator(self) -> Optional[Agent]:
        """Read the Agent that initiated current asynchronous context."""
        if self._initiator_state == "disposed":
            return None
        return _CURRENT_INITIATOR.get()

    currentInitiator = current_initiator

    def require_initiator(self) -> Agent:
        if self._initiator_state == "disposed":
            raise RuntimeError("agent initiator scope is disposed")
        initiator = self.current_initiator()
        if initiator is None:
            raise RuntimeError("no initiating agent is active")
        return initiator

    requireInitiator = require_initiator

    def _enter_initiator_run(self) -> None:
        if self._initiator_state != "active":
            raise RuntimeError(f"cannot enter agent initiator scope while {self._initiator_state}")
        self._active_initiator_runs += 1

    def _leave_initiator_run(self) -> None:
        self._active_initiator_runs = max(0, self._active_initiator_runs - 1)
        if self._active_initiator_runs == 0 and self._initiator_state == "closing":
            self._initiator_state = "disposed"
            if self._initiator_drain is not None:
                self._initiator_drain.set()

    def with_initiator(self, agent: Agent, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run callable within initiator scope."""
        self._enter_initiator_run()
        token = _CURRENT_INITIATOR.set(agent)
        try:
            return func(*args, **kwargs)
        finally:
            _CURRENT_INITIATOR.reset(token)
            self._leave_initiator_run()

    withInitiator = with_initiator

    async def with_initiator_async(self, agent: Agent, coro: Any) -> Any:
        """Run coroutine within initiator scope."""
        self._enter_initiator_run()
        token = _CURRENT_INITIATOR.set(agent)
        try:
            return await coro
        finally:
            _CURRENT_INITIATOR.reset(token)
            self._leave_initiator_run()

    def without_initiator(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run operation in a boundary that hides any inherited initiating Agent."""
        self._enter_initiator_run()
        token = _CURRENT_INITIATOR.set(None)
        try:
            return func(*args, **kwargs)
        finally:
            _CURRENT_INITIATOR.reset(token)
            self._leave_initiator_run()

    withoutInitiator = without_initiator

    def close_initiators(self) -> None:
        if self._initiator_state != "active":
            return
        if self._active_initiator_runs == 0:
            self._initiator_state = "disposed"
        else:
            self._initiator_state = "closing"

    closeInitiators = close_initiators

    async def dispose_initiators(self) -> None:
        self.close_initiators()
        if self._initiator_state != "disposed":
            if self._initiator_drain is None:
                self._initiator_drain = asyncio.Event()
            await self._initiator_drain.wait()
            self._initiator_state = "disposed"

    disposeInitiators = dispose_initiators

    def set_factory(self, factory: Any) -> Callable[[], None]:
        if self._factory is not None:
            raise RuntimeError("an agent factory is already registered")
        self._factory = factory

        def disposer():
            self._factory = None

        if self.ctx:
            self.ctx.effect(disposer)
        return disposer

    setFactory = set_factory

    def enter(
        self,
        agent: Agent,
        owner: Optional[Agent] = None,
        creator: Optional[Agent] = None,
    ) -> Callable[[], None]:
        sid = agent.id
        if sid != agent.session.id:
            raise ValueError(f'agent id "{sid}" does not match session id "{agent.session.id}"')
        if sid in self._store:
            raise ValueError(f'agent "{sid}" is already registered')

        effective_owner = creator if creator is not None else owner
        entry = _AgentEntry(agent=agent, owner=effective_owner)
        self._store[sid] = entry
        entered = True

        def detach():
            nonlocal entered
            if not entered:
                return
            entered = False
            if entry.announcing:
                entry.detach_requested = True
                return
            self._detach_entered(entry)

        return detach

    def _detach_entered(self, entry: _AgentEntry) -> None:
        entry.detach_requested = False
        if self._store.get(entry.id) is not entry:
            return
        self._store.pop(entry.id, None)
        if not entry.announced:
            return
        if self.ctx:
            self.ctx.emit("agent/disposed", {"agent": entry.agent})

    def announce(self, agent: Agent) -> None:
        entry = self._store.get(agent.id)
        if entry is None or entry.agent is not agent:
            raise RuntimeError(f'agent "{agent.id}" is not live in this registry')
        if entry.announced or entry.announcing:
            raise RuntimeError(f'agent "{entry.id}" was already announced')

        entry.announcing = True
        entry.announced = True
        try:
            if self.ctx:
                self.ctx.emit("agent/created", {"agent": entry.agent})
        finally:
            entry.announcing = False
            if entry.detach_requested:
                self._detach_entered(entry)

    def register(self, agent: Agent) -> Callable[[], None]:
        owner = self.current_initiator()
        detach = self.enter(agent, owner=owner)
        try:
            self.announce(agent)
        except Exception:
            detach()
            raise

        def disposer():
            detach()

        if self.ctx:
            self.ctx.effect(disposer)
        return disposer

    def get(self, session_id: str) -> Optional[Agent]:
        entry = self._store.get(session_id)
        return entry.agent if entry else None

    def is_owned_by(self, session_id: str, owner: Agent) -> bool:
        entry = self._store.get(session_id)
        return entry.owner == owner if entry else False

    isOwnedBy = is_owned_by

    def list(self) -> List[Agent]:
        return [entry.agent for entry in self._store.values()]

    def roots(self) -> List[Agent]:
        return [entry.agent for entry in self._store.values() if entry.owner is None]

    async def create(
        self,
        session_id: Optional[Union[str, Dict[str, Any]]] = None,
        options: Optional[Union[AgentOptions, Dict[str, Any]]] = None,
        meta: Optional[Dict[str, Any]] = None,
        setup: Optional[Callable[[Context], Any]] = None,
        **kwargs: Any,
    ) -> AgentHandle:
        import inspect
        if isinstance(session_id, dict):
            req = session_id
            sid = req.get("sessionId") or req.get("session_id")
            opts = req.get("options") or req.get("agentOptions") or req.get("agent_options")
            m = req.get("meta")
            s = req.get("setup")
            return await self.create(session_id=sid, options=opts, meta=m, setup=s)

        sid = session_id or kwargs.get("sessionId")
        opts_raw = options or kwargs.get("agentOptions") or kwargs.get("agent_options")
        opts = (
            AgentOptions(
                provider=opts_raw.get("provider"),
                model=opts_raw.get("model"),
                max_tokens=opts_raw.get("maxTokens") or opts_raw.get("max_tokens"),
                reasoning_effort=opts_raw.get("reasoningEffort") or opts_raw.get("reasoning_effort"),
            )
            if isinstance(opts_raw, dict)
            else opts_raw
        )
        m = meta or kwargs.get("meta")
        s = setup or kwargs.get("setup")

        if self._factory is None:
            raise RuntimeError("no agent factory registered (load an agent-loop plugin)")
        res = self._factory.create_agent(
            session_id=sid,
            options=opts,
            meta=m,
            setup=s,
        )
        if inspect.isawaitable(res):
            return await res
        return res

    async def resume(
        self,
        resume_session_id: Union[str, Dict[str, Any]],
        options: Optional[Union[AgentOptions, Dict[str, Any]]] = None,
        setup: Optional[Callable[[Context], Any]] = None,
        **kwargs: Any,
    ) -> AgentHandle:
        if isinstance(resume_session_id, dict):
            req = resume_session_id
            rsid = req.get("resumeSessionId") or req.get("resume_session_id")
            opts = req.get("options") or req.get("agentOptions") or req.get("agent_options")
            s = req.get("setup")
            return await self.resume(resume_session_id=rsid, options=opts, setup=s)

        rsid = resume_session_id or kwargs.get("resumeSessionId")
        opts_raw = options or kwargs.get("agentOptions") or kwargs.get("agent_options")
        opts = (
            AgentOptions(
                provider=opts_raw.get("provider"),
                model=opts_raw.get("model"),
                max_tokens=opts_raw.get("maxTokens") or opts_raw.get("max_tokens"),
                reasoning_effort=opts_raw.get("reasoningEffort") or opts_raw.get("reasoning_effort"),
            )
            if isinstance(opts_raw, dict)
            else opts_raw
        )
        s = setup or kwargs.get("setup")

        if self._factory is None:
            raise RuntimeError("no agent factory registered (load an agent-loop plugin)")
        return await self._factory.resume(
            resume_session_id=rsid,
            options=opts,
            setup=s,
        )


class AgentPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent`: Core Agent handle & registry service.
    """

    id = "agent"
    name = "@deepseek-ai/dsh-agent"

    def apply(self, ctx: Context) -> None:
        if not ctx.has("agents"):
            registry = AgentRegistry(ctx=ctx)
            ctx.set_service("agents", registry)
