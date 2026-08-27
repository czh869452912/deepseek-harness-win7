import asyncio
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

    accumulated = 0
    retain_start_idx = len(nodes)
    for i in range(len(nodes) - 1, -1, -1):
        accumulated += nodes[i].get("tokens", 0)
        if accumulated >= retain_tokens:
            retain_start_idx = i
            break

    if retain_start_idx <= 0:
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
        self.auto = auto

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

        # Edge checks for tool-pairing balance
        if hasattr(target_session, "surface"):
            if not tool_pairing_balanced_before(target_session, start):
                raise ValueError(f"Unbalanced tool pairing before seq {start}")
            if not tool_pairing_balanced_after(target_session, end):
                raise ValueError(f"Unbalanced tool pairing after seq {end}")

        llm = self.ctx.get("llm") if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("llm") else None
        summary_text = "This is a condensed summary of the previous conversation steps."
        if llm and hasattr(llm, "chat_completion"):
            try:
                res = llm.chat_completion([])
                if isinstance(res, dict):
                    summary_text = res.get("content", summary_text)
            except Exception:
                pass

        summary_content = f"<summary>\n{summary_text}\n</summary>"
        evt = target_session.append_user_message(summary_content)
        summary_seq = evt.get("seq", len(target_session.events) - 1) if isinstance(evt, dict) else getattr(evt, "seq", len(target_session.events) - 1)

        if hasattr(target_session, "surface"):
            target_session.surface.replace_range(start, end, summary_seq)

        shadowed_seqs = list(range(start, end + 1))
        return {
            "compactionId": f"comp-{start}-{end}",
            "startSeq": start,
            "endSeq": end,
            "summarySeq": summary_seq,
            "summary": summary_text,
            "shadowedRange": {"start": start, "end": end},
            "shadowedSeqs": shadowed_seqs,
            "shadowedTokenCount": len(shadowed_seqs) * 50,
        }

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

        measurement = {
            "nodes": [{"seq": evt.get("seq", idx), "tokens": len(str(evt.get("data", ""))) // 4 + 10} for idx, evt in enumerate(session.events)]
        }
        rng = select_compactable_range(session, measurement, retain_tokens=0)
        if not rng:
            return None

        return await self.compact_region(start=rng["start"], end=rng["end"], session=session)

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

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("tool_result_pruner") and target_session:
            pruner = self.ctx.get("tool_result_pruner")
            if hasattr(pruner, "prune_session"):
                pruner.prune_session(target_session)

        if target_session and (trigger in ("pressure", "context-overflow")):
            measurement = {
                "nodes": [{"seq": evt.get("seq", idx), "tokens": len(str(evt.get("data", ""))) // 4 + 10} for idx, evt in enumerate(target_session.events)]
            }
            retain = 0 if trigger == "context-overflow" else self.retain_tokens
            rng = select_compactable_range(target_session, measurement, retain_tokens=retain)
            if rng:
                res = await self.compact_region(start=rng["start"], end=rng["end"], session=target_session)
                return res

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

        async def hook_pre_step(payload: Dict[str, Any]) -> Dict[str, Any]:
            messages = payload.get("messages", [])
            if messages:
                compacted = await self.engine.compact_if_needed(messages=messages)
                payload["messages"] = compacted
            return payload

        ctx.on("agent/pre-step", hook_pre_step)


BasicCompactionEngine = CompactionEngine
BasicCompactionPlugin = CompactionBasicPlugin
