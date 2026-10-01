import asyncio
import logging
from typing import Any, Dict, Optional
from weakref import WeakKeyDictionary, ref

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.compaction.compaction_basic.config import (
    ResolvedCompactionConfig, TargetPressureConfigError, resolve_target_policy, resolve_compact_spec,
)
from dsh.compaction.tool_pairing import tool_pairing_balanced_before
from dsh.core.cancellation import aborted


def routed_target(session):
    config = (session.request_header() or {}).get("config", {})
    if not config.get("provider") or not config.get("model"):
        return None
    return dict(provider=config["provider"], model=config["model"])


def conversation_target(agent):
    target = routed_target(agent.session) if agent is not None else None
    if target is not None:
        return target
    options = getattr(agent, "options", None)
    provider, model = getattr(options, "provider", None), getattr(options, "model", None)
    return dict(provider=provider, model=model) if provider and model else None


class ManualCompactionError(Exception):
    """
    Expected manual compaction failure suitable for a direct command result.
    Error codes: 'busy', 'cancelled', 'changed', 'summary', 'commit', 'persistence'.
    """

    def __init__(self, code: str, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.cause = cause


def select_compactable_range(
    session: Any,
    measurement: Dict[str, Any],
    retain_tokens: int = 8000,
    **kwargs: Any,
) -> Optional[Dict[str, int]]:
    nodes = measurement.get("nodes", [])
    if not nodes:
        return None

    if [node["seq"] for node in nodes] != list(session.surface.nodes):
        raise ValueError("compaction: token-meter surface does not match the current session surface")

    accumulated = 0
    retain_start_idx = 0
    for i in range(len(nodes) - 1, -1, -1):
        accumulated += nodes[i].get("tokens", 0)
        if accumulated >= retain_tokens:
            retain_start_idx = i
            break

    if retain_start_idx <= 0:
        return None

    while retain_start_idx > 0 and not tool_pairing_balanced_before(session, nodes[retain_start_idx]["seq"]):
        retain_start_idx -= 1
    if retain_start_idx == 0:
        return None

    compactable_nodes = nodes[:retain_start_idx]
    if not compactable_nodes:
        return None

    return {
        "start": compactable_nodes[0]["seq"],
        "end": compactable_nodes[-1]["seq"],
    }


class CompactionEngine(Service):
    """
    Abstract / base Compaction Engine service mounted at ctx.compaction.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        ctx: Optional[Any] = None,
    ):
        if ctx is not None:
            super().__init__(ctx, "compaction")
        else:
            self.ctx = None

        self.resolved_config = ResolvedCompactionConfig(config)
        self.config = self.resolved_config.values
        self.auto = self.config["auto"]
        self._warned_pressure_targets = set()
        self._overflow_retries = WeakKeyDictionary()
        self._overflow_agents = WeakKeyDictionary()
        if ctx is not None and self.auto:
            self.register_automatic_compaction()

    def register_automatic_compaction(self):
        ctx = self.ctx
        logger = logging.getLogger("compaction-basic")

        async def pre_step(payload, next_fn):
            signal = payload.get("signal")
            if not aborted(signal):
                try:
                    await self.compact_if_needed(payload["agent"], "pressure", signal)
                except Exception as error:
                    if isinstance(error, TargetPressureConfigError):
                        if error.target_key in self._warned_pressure_targets:
                            return await next_fn()
                        self._warned_pressure_targets.add(error.target_key)
                    logger.warning("step compaction failed: %s; continuing the turn", error)
            return await next_fn()

        def status(payload):
            if payload["status"] == "idle":
                self._overflow_retries.pop(payload["agent"], None)

        def session_event(session, event):
            if event["type"] == "assistant/message":
                weak_agent = self._overflow_agents.get(session)
                agent = weak_agent() if weak_agent is not None else None
                if agent is not None:
                    self._overflow_retries.pop(agent, None)

        async def request_error(payload, next_fn):
            signal = payload.get("signal")
            if payload["failure"]["code"] != "CONTEXT_WINDOW_EXCEEDED" or aborted(signal):
                return await next_fn()
            agent = payload["agent"]
            self._overflow_agents[agent.session] = ref(agent)
            target = routed_target(agent.session)
            if target is None:
                return await next_fn()
            policy = resolve_target_policy(self.config, target)
            retries = self._overflow_retries.get(agent, 0)
            if retries >= policy["maxOverflowRetries"]:
                return await next_fn()
            generation = agent.session.surface.replace_generation
            try:
                await self.compact_if_needed(agent, "context-overflow", signal)
            except asyncio.CancelledError:
                if aborted(signal):
                    return await next_fn()
                raise
            except Exception as error:
                if not aborted(signal) and agent.session.surface.replace_generation > generation:
                    logger.warning("context-overflow compaction failed after durable surface progress: %s; retrying from the replacement surface", error)
                else:
                    logger.warning("context-overflow compaction failed: %s; preserving the original request error", error)
                    return await next_fn()
            if aborted(signal) or agent.session.surface.replace_generation <= generation:
                return await next_fn()
            self._overflow_retries[agent] = retries + 1
            return dict(kind="retry")

        ctx.on("agent/pre-step", pre_step)
        ctx.on("agent/status", status)
        ctx.on("session/event", session_event)
        ctx.on("agent/request-error", request_error)

    async def summarize(self, input, agent, signal=None):
        from dsh.compaction.native_summary import summarize
        return await summarize(self, input, agent, signal)

    async def compact_region(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        target_session = kwargs.get("session")
        agent = kwargs.get("agent")
        signal = kwargs.get("signal")

        if len(args) >= 1 and hasattr(args[0], "surface"):
            target_session = args[0]
            start = int(args[1]) if len(args) > 1 else int(kwargs.get("start", 0))
            end = int(args[2]) if len(args) > 2 else int(kwargs.get("end", 0))
        elif len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
            start = int(args[0])
            end = int(args[1])
            if len(args) >= 3 and not target_session:
                if hasattr(args[2], "session"):
                    agent = args[2]
                    target_session = agent.session
                elif hasattr(args[2], "surface"):
                    target_session = args[2]
            if len(args) >= 4:
                signal = args[3]
        else:
            start = int(kwargs.get("start", 0))
            end = int(kwargs.get("end", 0))

        if not target_session and agent and hasattr(agent, "session"):
            target_session = agent.session

        if not target_session:
            raise RuntimeError("Compaction target session is missing")

        from dsh.compaction.transaction import compact
        return await compact(self, target_session, start, end, agent=agent,
                             signal=signal, manual=kwargs.get("manual", False),
                             source_command_id=kwargs.get("source_command_id"), flush=kwargs.get("flush"))

    compact_surface_region = compact_region
    compactRegion = compact_region

    async def compact_now(
        self,
        agent: Optional[Any] = None,
        signal: Optional[Any] = None,
        source_command_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        from dsh.compaction.transaction import check_cancel
        check_cancel(signal)
        session = agent.session if agent and hasattr(agent, "session") else None
        if agent is None or session is None:
            raise ManualCompactionError("busy", "manual compaction requires an idle agent")

        from dsh.core.abort import AbortController
        from dsh.core.cancellation import subscribe_abort
        entered = False

        async def perform(maintenance):
            nonlocal entered
            entered = True
            control = AbortController()
            origin = []
            def relay(source, reason):
                if not control.signal.aborted:
                    origin.append(source)
                    control.abort(reason)
            disposers = [subscribe_abort(maintenance, lambda reason: relay("agent", reason)),
                         subscribe_abort(signal, lambda reason: relay("caller", reason))]
            try:
                check_cancel(control.signal)
                measurement = self.ctx.get("tokenMeter").measure(session)
                rng = select_compactable_range(session, measurement, retain_tokens=0)
                if not rng:
                    return None
                return await self.compact_region(start=rng["start"], end=rng["end"], session=session,
                                                 agent=agent, signal=control.signal, manual=True,
                                                 source_command_id=source_command_id, flush=session.flush)
            except BaseException as error:
                if origin == ["agent"]:
                    raise ManualCompactionError("cancelled", "manual compaction was cancelled", error) from error
                check_cancel(control.signal)
                raise
            finally:
                for dispose in disposers:
                    dispose()
        if agent.status != "idle":
            raise ManualCompactionError("busy", "manual compaction requires an idle agent")
        try:
            return await agent.run_maintenance(perform)
        except Exception as error:
            if not entered:
                raise ManualCompactionError("busy", "manual compaction requires an idle agent with no waking queued work", error) from error
            raise

    compactNow = compact_now

    async def compact_if_needed(
        self,
        agent: Optional[Any] = None,
        trigger: str = "pressure",
        signal: Optional[Any] = None,
        session: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        target_session = session or (agent.session if agent and hasattr(agent, "session") else None)

        target = routed_target(target_session) if target_session is not None else None
        if target is None:
            return None
        policy = resolve_target_policy(self.config, target)
        meter = self.ctx.get("tokenMeter")
        if meter is None:
            raise RuntimeError("compaction requires tokenMeter")
        measurement = meter.measure(target_session)
        if trigger not in ("pressure", "context-overflow"):
            raise ValueError("unknown compaction trigger: " + str(trigger))
        pruner = self.ctx.get("toolResultPruner")
        if trigger == "context-overflow":
            if pruner is not None:
                pruner.prune_session(target_session)
                measurement = meter.measure(target_session)
            rng = select_compactable_range(target_session, measurement, retain_tokens=0)
            return (await self.compact_region(start=rng["start"], end=rng["end"], session=target_session,
                                             agent=agent, signal=signal)) if rng else None

        info = await self.ctx.get("llm").resolve_model_info(target["provider"], target["model"], signal)
        from dsh.compaction.transaction import entry_state
        if entry_state(target_session)[1] is not None:
            raise ValueError("automatic pressure compaction: session already has active compaction")
        context = info.get("context")
        if context is None:
            key = target["provider"] + "/" + target["model"]
            raise TargetPressureConfigError(key, "compaction-basic: no context capacity for {}; configure contextWindow on that adapter model".format(key))
        spec = resolve_compact_spec(policy, context.get("contextWindow"))
        if measurement["totalTokens"] < spec["thresholdTokens"]:
            return None
        if pruner is not None:
            pruner.prune_session(target_session)
            measurement = meter.measure(target_session)
        if measurement["totalTokens"] < spec["thresholdTokens"]:
            return None
        result = None
        for _ in range(int(spec["compactionRetries"]) + 1):
            rng = select_compactable_range(target_session, measurement, retain_tokens=spec["retainTokens"])
            if rng is None:
                if result is None:
                    return None
                break
            result = await self.compact_region(start=rng["start"], end=rng["end"], session=target_session,
                                             agent=agent, signal=signal)
            measurement = meter.measure(target_session)
            if measurement["totalTokens"] < spec["thresholdTokens"]:
                return result
        raise RuntimeError("compaction still above threshold after {} compaction attempts ({} estimated tokens >= threshold {})".format(
            spec["compactionRetries"] + 1, measurement["totalTokens"], spec["thresholdTokens"]))

    compactIfNeeded = compact_if_needed


class CompactionBasicPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-compaction-basic`: Handles automatic token threshold compaction.
    """

    id = "compaction-basic"
    name = "@deepseek-ai/dsh-compaction-basic"
    inject = ["llm", "tokenMeter", "sessions"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.engine = CompactionEngine(config)

    def apply(self, ctx: Any) -> None:
        self.engine.ctx = ctx
        ctx.set_service("compaction", self.engine)
        if self.engine.auto:
            self.engine.register_automatic_compaction()


BasicCompactionEngine = CompactionEngine
BasicCompactionPlugin = CompactionBasicPlugin
