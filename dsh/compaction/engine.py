import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.compaction.compaction_basic.config import ResolvedCompactionConfig
from dsh.compaction.compaction_basic.region import identify_compaction_region
from dsh.compaction.compaction_basic.summarizer import summarize_compactable_messages
from dsh.compaction.tool_pairing import tool_pairing_balanced_before, tool_pairing_balanced_after


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
        threshold_tokens: Optional[int] = None,
        retain_tokens: Optional[int] = None,
        keep_recent_messages: Optional[int] = None,
        auto: bool = True,
        **kwargs: Any,
    ):
        if ctx is not None:
            super().__init__(ctx, "compaction")
            ctx.set_service("compaction_engine", self)
        else:
            self.ctx = None

        self.resolved_config = ResolvedCompactionConfig(config)
        self.threshold_tokens = threshold_tokens if threshold_tokens is not None else self.resolved_config.threshold_tokens
        self.retain_tokens = retain_tokens if retain_tokens is not None else self.resolved_config.retain_tokens
        self.keep_recent_messages = keep_recent_messages if keep_recent_messages is not None else self.resolved_config.keep_recent_messages
        self.auto = (config or {}).get("auto", auto)

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4

    async def compact_region(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        target_session = kwargs.get("session")
        agent = kwargs.get("agent")

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
        else:
            start = int(kwargs.get("start", 0))
            end = int(kwargs.get("end", 0))

        if not target_session and agent and hasattr(agent, "session"):
            target_session = agent.session

        if not target_session and self.ctx and hasattr(self.ctx, "has") and self.ctx.has("sessions"):
            store = self.ctx.get("sessions")
            if hasattr(store, "get"):
                target_session = store.get("default-session")

        if not target_session:
            raise RuntimeError("Compaction target session is missing")

        from dsh.compaction.transaction import compact
        return await compact(self, target_session, start, end, agent=agent,
                             signal=kwargs.get("signal"), manual=kwargs.get("manual", False),
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
        session = agent.session if agent and hasattr(agent, "session") else None
        if not session and self.ctx and hasattr(self.ctx, "has") and self.ctx.has("sessions"):
            store = self.ctx.get("sessions")
            if hasattr(store, "get"):
                session = store.get("default-session")

        if not session:
            return None

        if agent is None:
            raise ManualCompactionError("busy", "manual compaction requires an idle agent")

        from dsh.core.cancellation import aborted
        class CombinedSignal:
            @property
            def aborted(self):
                return aborted(signal) or aborted(self.maintenance)

        async def perform(maintenance):
            combined = CombinedSignal()
            combined.maintenance = maintenance
            from dsh.compaction.transaction import check_cancel
            check_cancel(combined)
            measurement = self.ctx.get("token_meter").measure(session)
            rng = select_compactable_range(session, measurement, retain_tokens=0)
            if not rng:
                return None
            return await self.compact_region(start=rng["start"], end=rng["end"], session=session,
                                             agent=agent, signal=combined, manual=True,
                                             source_command_id=source_command_id, flush=session.flush)
        if agent.status != "idle":
            raise ManualCompactionError("busy", "manual compaction requires an idle agent")
        return await agent.run_maintenance(perform)

    compactNow = compact_now

    async def compact_if_needed(
        self,
        agent: Optional[Any] = None,
        trigger: str = "pressure",
        signal: Optional[Any] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        session: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        target_session = session or (agent.session if agent and hasattr(agent, "session") else None)

        if not target_session and self.ctx and hasattr(self.ctx, "has") and self.ctx.has("sessions"):
            store = self.ctx.get("sessions")
            if hasattr(store, "get"):
                target_session = store.get("default-session")
                if not target_session and hasattr(store, "_sessions") and store._sessions:
                    target_session = next(iter(store._sessions.values()))

        if target_session and trigger in ("pressure", "context-overflow"):
            meter = self.ctx.get("token_meter")
            if meter is None:
                raise RuntimeError("compaction requires token_meter")
            measurement = meter.measure(target_session)
            if trigger == "pressure" and measurement["total_tokens"] <= self.threshold_tokens:
                return {"status": "no_compaction_needed"}
            pruner = self.ctx.get("tool_result_pruner")
            if pruner is not None:
                pruner.prune_session(target_session)
                measurement = meter.measure(target_session)
                if trigger == "pressure" and measurement["total_tokens"] <= self.threshold_tokens:
                    return {"status": "no_compaction_needed"}
            retain = 0 if trigger == "context-overflow" else self.retain_tokens
            rng = select_compactable_range(target_session, measurement, retain_tokens=retain)
            if rng:
                return await self.compact_region(start=rng["start"], end=rng["end"], session=target_session,
                                                 agent=agent, signal=signal)
            return {"status": "no_compaction_needed"}

        target_msgs = messages
        if target_msgs is None and target_session and hasattr(target_session, "events"):
            target_msgs = target_session.events

        if target_msgs is None:
            return {"status": "skipped"}

        est_tokens = self.estimate_tokens(target_msgs)
        if est_tokens <= self.threshold_tokens and trigger != "context-overflow":
            return target_msgs if messages is not None else {"status": "no_compaction_needed"}

        system_prefix, compactable_region, preserved_tail = identify_compaction_region(
            target_msgs, keep_recent_messages=self.keep_recent_messages
        )

        if not compactable_region:
            return target_msgs if messages is not None else {"status": "no_compaction_needed"}

        summary_text = summarize_compactable_messages(compactable_region)
        summary_message = {
            "role": "user",
            "content": f"[Compaction Summary]:\n{summary_text}",
        }

        compacted = system_prefix + [summary_message] + preserved_tail

        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("compaction/compacted", {
                "before_tokens": est_tokens,
                "after_tokens": self.estimate_tokens(compacted),
                "messages_reduced": len(target_msgs) - len(compacted),
            })

        if messages is not None:
            return compacted

        return {"status": "compacted", "reduced": len(target_msgs) - len(compacted)}

    compactIfNeeded = compact_if_needed


class CompactionBasicPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-compaction-basic`: Handles automatic token threshold compaction.
    """

    id = "compaction-basic"
    name = "@deepseek-ai/dsh-compaction-basic"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.engine = CompactionEngine(config)

    def apply(self, ctx: Any) -> None:
        self.engine.ctx = ctx
        ctx.set_service("compaction_engine", self.engine)
        ctx.set_service("compaction", self.engine)

        async def hook_pre_step(payload: Dict[str, Any], next_fn=None) -> Dict[str, Any]:
            agent = payload.get("agent")
            if agent is not None and self.engine.auto:
                try:
                    await self.engine.compact_if_needed(agent=agent, signal=payload.get("signal") or getattr(agent, "_cancel_event", None))
                except Exception:
                    logging.getLogger("compaction-basic").warning("step compaction failed; continuing the turn", exc_info=True)
            return await next_fn() if next_fn is not None else payload

        ctx.on("agent/pre-step", hook_pre_step)


BasicCompactionEngine = CompactionEngine
BasicCompactionPlugin = CompactionBasicPlugin
