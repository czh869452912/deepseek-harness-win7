"""
Compaction Engine & Basic Compaction Seam mounted at `ctx.compaction`.
Provides balanced range selection, bracket lock transactions, and prefix-cached LLM summarization.
"""

import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.surface import (
    tool_pairing_balanced_after,
    tool_pairing_balanced_before,
)


SUMMARY_PROMPT = (
    "Provide a concise summary of the conversation and tool execution history above. "
    "Focus on user goals, key decisions, files modified/read, and the current task status. "
    "Do not include unnecessary details."
)


def select_compactable_range(
    session: Any,
    measurement: Dict[str, Any],
    retain_tokens: int,
) -> Optional[Dict[str, int]]:
    """
    Resolve the next head-anchored range while retaining a priced recent tail
    and never splitting an assistant tool-call/result pair.
    """
    surface_nodes = session.surface.nodes
    priced_nodes = measurement.get("nodes", [])

    if not priced_nodes or len(surface_nodes) == 0:
        return None

    accumulated = 0
    keep_from_idx = len(priced_nodes)

    for index in range(len(priced_nodes) - 1, -1, -1):
        accumulated += priced_nodes[index].get("tokens", 0)
        keep_from_idx = index
        if accumulated >= retain_tokens:
            break

    if keep_from_idx == 0:
        return None

    # Step back until tool pairing before keep_from_idx is balanced
    while keep_from_idx > 0:
        seq = surface_nodes[keep_from_idx]
        if tool_pairing_balanced_before(session.events, surface_nodes, seq):
            break
        keep_from_idx -= 1

    if keep_from_idx == 0:
        return None

    first = surface_nodes[0]
    cutoff = surface_nodes[keep_from_idx - 1]
    return {"start": first, "end": cutoff}


class CompactionEngine(ABC):
    """
    Abstract compaction service seam.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx

    @abstractmethod
    async def compact_if_needed(
        self,
        agent: Any,
        trigger: str,
        signal: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def compact_region(
        self,
        start: int,
        end: int,
        agent: Any,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def compact_now(self, agent: Any) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class BasicCompactionEngine(CompactionEngine):
    """
    Basic replay-aware compaction engine.
    """

    def __init__(
        self,
        threshold_tokens: int = 80000,
        retain_tokens: int = 20000,
        auto: bool = True,
        ctx: Optional[Any] = None,
    ):
        super().__init__(ctx=ctx)
        self.threshold_tokens = threshold_tokens
        self.retain_tokens = retain_tokens
        self.auto = auto

        if self.ctx and self.auto:
            self._register_automatic_compaction()

    def _register_automatic_compaction(self) -> None:
        self.ctx.on("agent/pre-step", self._on_pre_step)

    async def _on_pre_step(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Hook into agent pre-step to perform pressure compaction if needed."""
        session = self.ctx.get("sessions")
        if session:
            try:
                await self.compact_if_needed(agent=None, trigger="pressure")
            except Exception as e:
                if self.ctx.logger:
                    self.ctx.logger.warn("automatic compaction failed: %s", str(e))
        return request_payload

    async def summarize_range(
        self,
        session: Any,
        shadowed_seqs: List[int],
    ) -> str:
        """
        Summarize the replayed conversation region using LLM.
        """
        llm = self.ctx.get("llm") if self.ctx else None
        if not llm:
            return "Summary of earlier session steps."

        region_messages = []
        events = session.events
        for seq in shadowed_seqs:
            if seq < len(events):
                event = events[seq]
                etype = event.get("type")
                edata = event.get("data", {})
                if etype == "user/message":
                    region_messages.append({"role": "user", "content": edata.get("content", "")})
                elif etype == "assistant/message":
                    msg = edata.get("message", edata)
                    region_messages.append(msg)
                elif etype == "tool/result":
                    region_messages.append({
                        "role": "tool",
                        "tool_call_id": edata.get("tool_call_id", ""),
                        "name": edata.get("name", ""),
                        "content": str(edata.get("result", "")),
                    })

        messages = [
            {"role": "system", "content": "You are a session compaction assistant."},
            *region_messages,
            {"role": "user", "content": SUMMARY_PROMPT},
        ]

        try:
            resp = llm.chat_completion(messages=messages, tools=None)
            return resp.get("content", "Conversation summary generated.")
        except Exception:
            return "Automated conversation summary."

    async def compact_surface_region(
        self,
        session: Any,
        start: int,
        end: int,
        owner_turn: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute the atomic compaction transaction over [start, end].
        """
        nodes = list(session.surface.nodes)
        if start not in nodes or end not in nodes:
            raise ValueError(f"compact_surface_region: start {start} or end {end} not in surface")

        start_idx = nodes.index(start)
        end_idx = nodes.index(end)
        if start_idx > end_idx:
            raise ValueError(f"compact_surface_region: start {start} is after end {end}")

        if not tool_pairing_balanced_before(session.events, nodes, start):
            raise ValueError(f"compact_surface_region: start seq {start} unbalanced")
        if not tool_pairing_balanced_after(session.events, nodes, end):
            raise ValueError(f"compact_surface_region: end seq {end} unbalanced")

        shadowed_seqs = nodes[start_idx : end_idx + 1]
        compaction_id = str(uuid.uuid4())

        meter = self.ctx.get("token_meter") if self.ctx else None
        shadowed_tokens = 0
        if meter:
            for s in shadowed_seqs:
                if s < len(session.events):
                    shadowed_tokens += meter.estimate_message(session.events[s].get("data", {}))

        # 1. Start Lock Event: compaction/start
        start_event = session.append(
            "compaction/start",
            {"compactionId": compaction_id, "turn": owner_turn},
            ignorable=True,
        )

        try:
            # 2. Summarize
            summary_text = await self.summarize_range(session, shadowed_seqs)

            # 3. Summary Record: compaction/summary
            summary_event = session.append(
                "compaction/summary",
                {
                    "compactionId": compaction_id,
                    "summary": summary_text,
                    "shadowedRange": {"start": start, "end": end},
                    "shadowedSeqs": shadowed_seqs,
                    "shadowedTokenCount": shadowed_tokens,
                },
                ignorable=True,
            )

            # 4. Replacement User Message
            framed_content = f"<summary>\n{summary_text}\n</summary>"
            checkpoint_message = {
                "role": "user",
                "content": framed_content,
                "source": {"kind": "compaction", "compactionId": compaction_id},
            }

            session.append(
                "user/message",
                checkpoint_message,
                surface_op={"op": "replace", "start": start, "end": end},
                source_event_seqs=[start_event["seq"], summary_event["seq"]] + shadowed_seqs,
            )

            # 5. End Lock Event: compaction/end
            end_event = session.append(
                "compaction/end",
                {"compactionId": compaction_id, "turn": owner_turn},
                ignorable=True,
            )

            return {
                "compactionId": compaction_id,
                "startSeq": start_event["seq"],
                "summarySeq": summary_event["seq"],
                "endSeq": end_event["seq"],
                "summary": summary_text,
                "shadowedRange": {"start": start, "end": end},
                "shadowedSeqs": shadowed_seqs,
                "shadowedTokenCount": shadowed_tokens,
            }

        except Exception as e:
            # Release lock with error
            session.append(
                "compaction/end",
                {"compactionId": compaction_id, "turn": owner_turn, "error": str(e)},
                ignorable=True,
            )
            raise e

    def _resolve_session(self, agent: Any = None) -> Optional[Any]:
        if agent and hasattr(agent, "session"):
            return agent.session
        sessions_svc = self.ctx.get("sessions") if self.ctx else None
        if hasattr(sessions_svc, "_sessions"):
            s = sessions_svc.get("default-session")
            if not s and sessions_svc._sessions:
                s = next(iter(sessions_svc._sessions.values()))
            return s
        return sessions_svc

    async def compact_region(
        self,
        start: int,
        end: int,
        agent: Any = None,
    ) -> Dict[str, Any]:
        session = self._resolve_session(agent)
        if not session:
            raise RuntimeError("no session available for compact_region")
        return await self.compact_surface_region(session, start, end)

    async def compact_if_needed(
        self,
        agent: Any = None,
        trigger: str = "pressure",
        signal: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        session = self._resolve_session(agent)
        if not session:
            return None

        meter = self.ctx.get("token_meter") if self.ctx else None
        if not meter:
            return None

        # 1. Run model-free tool result pruner first if present
        pruner = self.ctx.get("tool_result_pruner") if self.ctx else None
        if pruner:
            pruner.prune_session(session)

        measurement = meter.measure(session)
        total_tokens = measurement.get("total_tokens", 0)

        if trigger == "pressure" and total_tokens < self.threshold_tokens:
            return None

        # 2. Select compactable range
        retain = 0 if trigger == "context-overflow" else self.retain_tokens
        rng = select_compactable_range(session, measurement, retain)
        if not rng:
            return None

        return await self.compact_surface_region(session, rng["start"], rng["end"])

    async def compact_now(self, agent: Any = None) -> Optional[Dict[str, Any]]:
        return await self.compact_if_needed(agent=agent, trigger="manual")


class BasicCompactionPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-compaction-basic`: Basic compaction backend and policy.
    """

    id = "compaction-basic"
    name = "@deepseek-ai/dsh-compaction-basic"

    def __init__(
        self,
        threshold_tokens: int = 80000,
        retain_tokens: int = 20000,
        auto: bool = True,
    ):
        self.threshold_tokens = threshold_tokens
        self.retain_tokens = retain_tokens
        self.auto = auto

    def apply(self, ctx: Any) -> None:
        if not ctx.has("compaction"):
            engine = BasicCompactionEngine(
                threshold_tokens=self.threshold_tokens,
                retain_tokens=self.retain_tokens,
                auto=self.auto,
                ctx=ctx,
            )
            ctx.set_service("compaction", engine)
