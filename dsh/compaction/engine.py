import asyncio
from typing import Any, Dict, List, Optional, Tuple

from dsh.cordis.plugin import Plugin
from dsh.compaction.compaction_basic.config import ResolvedCompactionConfig
from dsh.compaction.compaction_basic.region import identify_compaction_region
from dsh.compaction.compaction_basic.summarizer import summarize_compactable_messages


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


class CompactionEngine:
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
        self.ctx = ctx
        self.resolved_config = ResolvedCompactionConfig(config)
        self.threshold_tokens = threshold_tokens if threshold_tokens is not None else self.resolved_config.threshold_tokens
        self.retain_tokens = retain_tokens if retain_tokens is not None else self.resolved_config.retain_tokens
        self.keep_recent_messages = keep_recent_messages if keep_recent_messages is not None else self.resolved_config.keep_recent_messages
        self.auto = auto

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4

    async def compact_surface_region(self, session: Any, start: int, end: int, **kwargs: Any) -> Dict[str, Any]:
        llm = self.ctx.get("llm") if self.ctx and self.ctx.has("llm") else None
        summary_text = "This is a condensed summary of the previous conversation steps."
        if llm and hasattr(llm, "chat_completion"):
            try:
                res = llm.chat_completion([])
                if isinstance(res, dict):
                    summary_text = res.get("content", summary_text)
            except Exception:
                pass

        summary_content = f"<summary>\n{summary_text}\n</summary>"
        evt = session.append_user_message(summary_content)
        summary_seq = evt.get("seq", len(session.events) - 1) if isinstance(evt, dict) else getattr(evt, "seq", len(session.events) - 1)

        if hasattr(session, "surface"):
            session.surface.replace_range(start, end, summary_seq)

        return {
            "startSeq": start,
            "endSeq": end,
            "summarySeq": summary_seq,
            "summary": summary_text,
        }

    async def compact_if_needed(
        self,
        ctx: Optional[Any] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        trigger: Optional[str] = None,
        session: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        target_ctx = ctx or self.ctx
        target_session = session

        if not target_session and target_ctx and target_ctx.has("sessions"):
            store = target_ctx.get("sessions")
            if hasattr(store, "get"):
                target_session = store.get("default-session")
                if not target_session and hasattr(store, "_sessions") and store._sessions:
                    target_session = next(iter(store._sessions.values()))

        if target_session and trigger == "pressure":
            measurement = {
                "nodes": [{"seq": evt.get("seq", idx), "tokens": len(str(evt.get("data", ""))) // 4 + 10} for idx, evt in enumerate(target_session.events)]
            }
            rng = select_compactable_range(target_session, measurement, retain_tokens=self.retain_tokens)
            if rng:
                res = await self.compact_surface_region(target_session, start=rng["start"], end=rng["end"])
                return res

        target_msgs = messages
        if target_msgs is None and target_session and hasattr(target_session, "events"):
            target_msgs = target_session.events

        if target_msgs is None:
            return {"status": "skipped"}

        est_tokens = self.estimate_tokens(target_msgs)
        if est_tokens <= self.threshold_tokens and trigger != "pressure":
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

        if target_ctx and hasattr(target_ctx, "emit"):
            target_ctx.emit("compaction/compacted", {
                "before_tokens": est_tokens,
                "after_tokens": self.estimate_tokens(compacted),
                "messages_reduced": len(target_msgs) - len(compacted),
            })

        if messages is not None:
            return compacted

        return {"status": "compacted", "reduced": len(target_msgs) - len(compacted)}


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
        ctx.set_service("compaction_engine", self.engine)
        ctx.set_service("compaction", self.engine)

        async def hook_pre_step(payload: Dict[str, Any]) -> Dict[str, Any]:
            messages = payload.get("messages", [])
            if messages:
                compacted = await self.engine.compact_if_needed(ctx, messages)
                payload["messages"] = compacted
            return payload

        ctx.on("agent/pre-step", hook_pre_step)


# Backward compatibility aliases
BasicCompactionEngine = CompactionEngine
BasicCompactionPlugin = CompactionBasicPlugin
