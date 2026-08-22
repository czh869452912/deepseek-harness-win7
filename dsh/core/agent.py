"""
Agent handle, Inbox integration, Initiator ContextVar scoping, and AgentRegistry.
1:1 aligned with official `@deepseek-ai/dsh-agent`.
"""

import asyncio
import contextvars
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
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
        max_tokens: Optional[int] = None,
    ):
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {}
        if self.provider is not None:
            res["provider"] = self.provider
        if self.model is not None:
            res["model"] = self.model
        if self.max_tokens is not None:
            res["maxTokens"] = self.max_tokens
        return res


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
    ):
        self.id = session.id
        self.session = session
        self.options = options or AgentOptions()
        self.ctx = ctx or Context()
        self.inbox = Inbox(session=self.session, ctx=self.ctx, agent=self)
        self._status: str = "idle"
        self._wake_event = asyncio.Event()
        self._cancel_cause: Optional[Dict[str, Any]] = None
        self._idle_futures: List[asyncio.Future] = []
        self._driver_task: Optional[asyncio.Task] = None

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, new_status: str) -> None:
        if self._status != new_status:
            self._status = new_status
            if self.ctx:
                self.ctx.emit("agent/status", {"agent": self, "status": new_status})
            if new_status == "idle":
                # Notify when_idle waiters
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
        msg_id = self.inbox.append(target, msg_dict)
        if wakeup:
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

    def cancel(self, cause: Optional[Dict[str, Any]] = None, keep_inbox: bool = False) -> None:
        """
        Abort active driver and optionally clear inbox.
        """
        self._cancel_cause = cause or {"kind": "user"}
        if not keep_inbox:
            self.inbox.clear()
        self._wake_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_cause is not None

    def take_cancel_cause(self) -> Optional[Dict[str, Any]]:
        cause = self._cancel_cause
        self._cancel_cause = None
        return cause

    async def when_idle(self) -> None:
        """Resolve when whole-agent activity reaches idle quiescence."""
        if self._status == "idle" and self.inbox.is_empty():
            return
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._idle_futures.append(fut)
        await fut

    async def run_maintenance(self, task_fn: Callable[[asyncio.Event], Any]) -> Any:
        """Run non-turn maintenance task in idle phase."""
        if self._status != "idle":
            raise RuntimeError(f'agent "{self.id}" already has active work')
        abort_event = asyncio.Event()
        res = task_fn(abort_event)
        if asyncio.iscoroutine(res):
            res = await res
        return res


class AgentHandle:
    """
    Owned agent capability handle returned by AgentRegistry.create / resume.
    """

    def __init__(self, agent: Agent, disposer: Callable[[], Any]):
        self.agent = agent
        self._disposer = disposer

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
    """

    def __init__(self, ctx: Optional[Context] = None):
        self.ctx = ctx
        self._store: Dict[str, _AgentEntry] = {}
        self._factory: Optional[Any] = None

    def current_initiator(self) -> Optional[Agent]:
        """Read the Agent that initiated current asynchronous context."""
        return _CURRENT_INITIATOR.get()

    def require_initiator(self) -> Agent:
        initiator = self.current_initiator()
        if initiator is None:
            raise RuntimeError("no initiating agent is active")
        return initiator

    def with_initiator(self, agent: Agent, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run callable within initiator scope."""
        token = _CURRENT_INITIATOR.set(agent)
        try:
            return func(*args, **kwargs)
        finally:
            _CURRENT_INITIATOR.reset(token)

    async def with_initiator_async(self, agent: Agent, coro: Any) -> Any:
        """Run coroutine within initiator scope."""
        token = _CURRENT_INITIATOR.set(agent)
        try:
            return await coro
        finally:
            _CURRENT_INITIATOR.reset(token)

    def without_initiator(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run operation in a boundary that hides any inherited initiating Agent."""
        token = _CURRENT_INITIATOR.set(None)
        try:
            return func(*args, **kwargs)
        finally:
            _CURRENT_INITIATOR.reset(token)

    def set_factory(self, factory: Any) -> Callable[[], None]:
        if self._factory is not None:
            raise RuntimeError("an agent factory is already registered")
        self._factory = factory

        def disposer():
            self._factory = None

        if self.ctx:
            self.ctx.effect(disposer)
        return disposer

    def enter(self, agent: Agent, owner: Optional[Agent] = None) -> Callable[[], None]:
        sid = agent.id
        if sid != agent.session.id:
            raise ValueError(f'agent id "{sid}" does not match session id "{agent.session.id}"')
        if sid in self._store:
            raise ValueError(f'agent "{sid}" is already registered')

        entry = _AgentEntry(agent=agent, owner=owner)
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
        self.announce(agent)

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

    def list(self) -> List[Agent]:
        return [entry.agent for entry in self._store.values()]

    def roots(self) -> List[Agent]:
        return [entry.agent for entry in self._store.values() if entry.owner is None]

    async def create(
        self,
        session_id: Optional[str] = None,
        options: Optional[AgentOptions] = None,
        meta: Optional[Dict[str, Any]] = None,
        setup: Optional[Callable[[Context], Any]] = None,
    ) -> AgentHandle:
        if self._factory is None:
            raise RuntimeError("no agent factory registered (load an agent-loop plugin)")
        return await self._factory.create_agent(
            session_id=session_id,
            options=options,
            meta=meta,
            setup=setup,
        )

    async def resume(
        self,
        resume_session_id: str,
        options: Optional[AgentOptions] = None,
        setup: Optional[Callable[[Context], Any]] = None,
    ) -> AgentHandle:
        if self._factory is None:
            raise RuntimeError("no agent factory registered (load an agent-loop plugin)")
        return await self._factory.resume(
            resume_session_id=resume_session_id,
            options=options,
            setup=setup,
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
