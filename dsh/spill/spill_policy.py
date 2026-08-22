"""
Plugin `@deepseek-ai/dsh-spill-policy`: Result transformer keeping oversized plain-text tool results out of model context.
"""

import math
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


def flatten_plain_text(content: Any) -> Optional[str]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") != "text":
                    return None
                text_parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                text_parts.append(block)
            else:
                return None
        return "".join(text_parts)
    return None


def preview(text: str, budget: int) -> Dict[str, Any]:
    text_bytes = text.encode("utf-8")
    if len(text_bytes) <= budget:
        return {"text": text, "omitted": 0}
    
    head_bytes = math.ceil(budget / 2)
    tail_bytes = math.floor(budget / 2)
    
    head_text = text_bytes[:head_bytes].decode("utf-8", errors="ignore")
    tail_text = text_bytes[len(text_bytes) - tail_bytes:].decode("utf-8", errors="ignore") if tail_bytes > 0 else ""
    omitted = len(text_bytes) - len(head_text.encode("utf-8")) - len(tail_text.encode("utf-8"))
    
    return {"text": head_text + tail_text, "omitted": max(0, omitted)}


def spill_notice(omitted_bytes: int, locator: str, retrieval_hint: str) -> str:
    return f"({omitted_bytes} bytes omitted. Full formatted result stored at: {locator}. {retrieval_hint})"


class SpillPolicyPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-spill-policy`: Keeps oversized plain-text tool results out of model context.
    """

    id = "spill-policy"
    name = "@deepseek-ai/dsh-spill-policy"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.max_inline_bytes: Optional[int] = cfg.get("maxInlineBytes", cfg.get("max_inline_bytes"))

    def apply(self, ctx: Any) -> None:
        if self.max_inline_bytes is None:
            return

        if not isinstance(self.max_inline_bytes, int) or self.max_inline_bytes < 0:
            raise ValueError(f"spill-policy: maxInlineBytes must be a non-negative integer (got {self.max_inline_bytes})")

        cap = self.max_inline_bytes

        async def spill_replacement(
            text: str,
            total_bytes: int,
            session_id: str,
            tool_name: str,
            call_id: str,
            label: str,
        ) -> Optional[str]:
            spill_store = ctx.get("spillStore") if ctx.has("spillStore") else None
            if not spill_store:
                return None

            try:
                ref = spill_store.save_text(
                    owner={"sessionId": session_id},
                    source={"toolName": tool_name, "callId": call_id, "label": label},
                    suggestedName=f"{tool_name}.txt",
                    content=text,
                )
            except Exception:
                return None

            locator = ref.get("locator", "")
            hint = ref.get("retrievalHint", "")
            
            notice_sample = spill_notice(total_bytes, locator, hint)
            reserve = len(notice_sample.encode("utf-8")) + 2
            preview_budget = max(0, cap - reserve)

            prev = preview(text, preview_budget)
            notice = spill_notice(prev["omitted"], locator, hint)

            prev_text = prev["text"]
            replaced_text = f"{prev_text}\n\n{notice}" if len(prev_text) > 0 else notice

            if len(replaced_text.encode("utf-8")) > cap:
                return None
            return replaced_text

        async def on_post_execute(exec_data: Any, result_data: Any, next_fn: Any) -> Any:
            decision = await next_fn()
            
            exec_name = getattr(exec_data, "name", "") if not isinstance(exec_data, dict) else exec_data.get("name", "")
            if exec_name == "read":
                return decision

            content = getattr(result_data, "content", None) if hasattr(result_data, "content") else (result_data.get("content") if isinstance(result_data, dict) else None)
            text = flatten_plain_text(content)
            if text is None:
                return decision

            total_bytes = len(text.encode("utf-8"))
            if total_bytes <= cap:
                return decision

            sess_id = getattr(exec_data, "session_id", "default") if not isinstance(exec_data, dict) else exec_data.get("session_id", "default")
            call_id = getattr(exec_data, "call_id", "c0") if not isinstance(exec_data, dict) else exec_data.get("call_id", "c0")

            replaced_text = await spill_replacement(text, total_bytes, sess_id, exec_name, call_id, "result")
            if replaced_text is None:
                return decision

            replaced = [{"type": "text", "text": replaced_text}]
            if isinstance(decision, dict):
                decision["content"] = replaced
                return decision
            elif hasattr(decision, "content"):
                decision.content = replaced
                return decision
            return {"kind": "accept", "content": replaced}

        ctx.on("tools/post-execute", on_post_execute, prepend=True)
