"""
Deterministic Model-Free Tool-Result Pruner Service mounted at `ctx.tool_result_pruner`.
"""

from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


PRUNE_MARKER = "\n... [pruned {removed} characters] ...\n"


class ToolResultPruner:
    """
    Deterministic head/middle/tail pruning for tool-result surface nodes.
    """

    def __init__(
        self,
        threshold_chars: int = 2000,
        head_chars: int = 500,
        tail_chars: int = 500,
        ctx: Optional[Any] = None,
    ):
        self.ctx = ctx
        self.threshold_chars = threshold_chars
        self.head_chars = head_chars
        self.tail_chars = tail_chars

    def measure_content(self, text: Any) -> int:
        if isinstance(text, str):
            return len(text)
        return len(str(text))

    def prune_content(self, text: str) -> Optional[str]:
        total_len = len(text)
        if total_len <= self.threshold_chars:
            return None

        head = text[: self.head_chars]
        tail = text[total_len - self.tail_chars :] if self.tail_chars > 0 else ""
        removed_count = total_len - self.head_chars - self.tail_chars
        marker = PRUNE_MARKER.format(removed=removed_count)
        return head + marker + tail

    def prune_session(self, session: Any) -> Dict[str, Any]:
        """
        Prune every over-budget tool result from current session surface.
        Emits compaction/prune shadow-pricing event before each replacement.
        """
        nodes = list(session.surface.nodes)
        events = session.events
        meter = self.ctx.get("token_meter") if self.ctx else None

        pruned_entries: List[Dict[str, Any]] = []
        chars_removed_total = 0

        for seq in nodes:
            if seq >= len(events):
                continue
            event = events[seq]
            if event.get("type") != "tool/result":
                continue

            edata = event.get("data", {})
            original_result = str(edata.get("result", edata.get("content", "")))
            pruned_result = self.prune_content(original_result)

            if pruned_result is not None:
                chars_before = len(original_result)
                chars_after = len(pruned_result)
                saved_chars = chars_before - chars_after
                chars_removed_total += saved_chars

                token_price = 0
                if meter:
                    token_price = meter.estimate_message(
                        {"role": "tool", "content": original_result}
                    )

                # 1. Append shadow-price event: compaction/prune
                session.append(
                    "compaction/prune",
                    {
                        "shadowedRange": {"start": seq, "end": seq},
                        "shadowedSeqs": [seq],
                        "shadowedTokenCount": token_price,
                    },
                    ignorable=True,
                )

                # 2. Append replacement tool/result
                replacement_data = dict(edata)
                replacement_data["result"] = pruned_result
                if "message" in replacement_data:
                    replacement_data["message"] = dict(replacement_data["message"])
                    replacement_data["message"]["content"] = pruned_result

                replacement = session.append(
                    "tool/result",
                    replacement_data,
                    surface_op={"op": "replace", "start": seq, "end": seq},
                    source_event_seqs=[seq],
                )

                pruned_entries.append({
                    "original_seq": seq,
                    "replacement_seq": replacement.get("seq"),
                    "chars_before": chars_before,
                    "chars_after": chars_after,
                })

        return {
            "pruned": pruned_entries,
            "chars_removed": chars_removed_total,
        }


class ToolResultPrunerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-compaction-tool-result-pruner`: Deterministic tool-result pruner.
    """

    id = "tool-result-pruner"
    name = "@deepseek-ai/dsh-compaction-tool-result-pruner"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        threshold_chars: int = 2000,
        head_chars: int = 500,
        tail_chars: int = 500,
    ):
        super().__init__(config)
        cfg = config or {}
        self.threshold_chars = int(cfg.get("thresholdChars", cfg.get("threshold_chars", threshold_chars)))
        self.head_chars = int(cfg.get("headChars", cfg.get("head_chars", head_chars)))
        self.tail_chars = int(cfg.get("tailChars", cfg.get("tail_chars", tail_chars)))

    def apply(self, ctx: Any) -> None:
        if not ctx.has("tool_result_pruner"):
            pruner = ToolResultPruner(
                threshold_chars=self.threshold_chars,
                head_chars=self.head_chars,
                tail_chars=self.tail_chars,
                ctx=ctx,
            )
            ctx.set_service("tool_result_pruner", pruner)
