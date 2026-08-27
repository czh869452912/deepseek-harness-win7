"""
Deterministic Model-Free Tool-Result Pruner Service mounted at `ctx.tool_result_pruner`.
"""

from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service

PRUNE_MARKER = "\n\n[... tool result middle pruned ...]\n\n"


def code_point_length(text: str) -> int:
    return len(text)


class ToolResultPruner(Service):
    """
    Deterministic head/middle/tail pruning for tool-result surface nodes.
    """

    def __init__(
        self,
        threshold_chars: Optional[int] = None,
        head_chars: Optional[int] = None,
        tail_chars: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
        ctx: Optional[Any] = None,
    ):
        if ctx is not None:
            super().__init__(ctx, "tool_result_pruner")
            ctx.set_service("toolResultPruner", self)
        else:
            self.ctx = None

        cfg = config or {}
        self.threshold_chars = (
            threshold_chars
            if threshold_chars is not None
            else int(cfg.get("thresholdChars", cfg.get("threshold_chars", 8192)))
        )
        self.head_chars = (
            head_chars
            if head_chars is not None
            else int(cfg.get("headChars", cfg.get("head_chars", 4096)))
        )
        self.tail_chars = (
            tail_chars
            if tail_chars is not None
            else int(cfg.get("tailChars", cfg.get("tail_chars", 1024)))
        )

    def measure_content(self, blocks_or_text: Any) -> int:
        if isinstance(blocks_or_text, str):
            return code_point_length(blocks_or_text)
        if isinstance(blocks_or_text, list):
            chars = 0
            for block in blocks_or_text:
                if isinstance(block, dict) and block.get("type") == "text":
                    chars += code_point_length(str(block.get("text", "")))
                elif isinstance(block, str):
                    chars += code_point_length(block)
            return chars
        return code_point_length(str(blocks_or_text))

    def prune_content(self, blocks_or_text: Any) -> Optional[Any]:
        if isinstance(blocks_or_text, str):
            text = blocks_or_text
            total_len = code_point_length(text)
            if total_len <= self.threshold_chars:
                return None
            removed_start = self.head_chars
            removed_end = total_len - self.tail_chars
            head = text[:removed_start]
            tail = text[removed_end:] if self.tail_chars > 0 else ""
            return head + PRUNE_MARKER + tail

        if isinstance(blocks_or_text, list):
            total_chars = self.measure_content(blocks_or_text)
            if total_chars <= self.threshold_chars:
                return None
            removed_start = self.head_chars
            removed_end = total_chars - self.tail_chars
            pruned: List[Dict[str, Any]] = []
            consumed = 0
            marker_inserted = False

            for block in blocks_or_text:
                if not isinstance(block, dict) or block.get("type") != "text":
                    pruned.append(block)
                    continue

                b_text = str(block.get("text", ""))
                b_len = code_point_length(b_text)
                block_start = consumed
                block_end = block_start + b_len
                head_end = max(0, min(b_len, removed_start - block_start))
                tail_start = max(0, min(b_len, removed_end - block_start))
                intersects_removed = block_start < removed_end and block_end > removed_start

                marker = PRUNE_MARKER if (intersects_removed and not marker_inserted) else ""
                if marker:
                    marker_inserted = True

                new_text = b_text[:head_end] + marker + b_text[tail_start:]
                if new_text:
                    pruned.append({**block, "text": new_text})
                consumed = block_end

            return pruned

        return None

    def prune_session(self, session: Any) -> Dict[str, Any]:
        """
        Prune every over-budget tool result from current session surface.
        Emits compaction/prune shadow-pricing event before each replacement.
        """
        nodes = list(session.surface.nodes)
        events = session.events
        meter = self.ctx.get("token_meter") if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("token_meter") else None

        pruned_entries: List[Dict[str, Any]] = []
        chars_removed_total = 0

        for seq in nodes:
            if seq >= len(events):
                continue
            event = events[seq]
            evt_dict = event if isinstance(event, dict) else (event.to_dict() if hasattr(event, "to_dict") else {})
            if evt_dict.get("type") != "tool/result":
                continue

            edata = evt_dict.get("data", {})
            raw_content = edata.get("result", edata.get("content", edata.get("message", {}).get("content", "")))
            
            pruned_content = self.prune_content(raw_content)

            if pruned_content is not None:
                chars_before = self.measure_content(raw_content)
                chars_after = self.measure_content(pruned_content)
                saved_chars = chars_before - chars_after
                chars_removed_total += saved_chars

                token_price = 0
                if meter:
                    msg_obj = edata.get("message", {"role": "tool", "content": str(raw_content)})
                    token_price = meter.estimate_message(msg_obj)

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
                if isinstance(raw_content, str):
                    replacement_data["result"] = pruned_content
                if "message" in replacement_data and isinstance(replacement_data["message"], dict):
                    replacement_data["message"] = dict(replacement_data["message"])
                    replacement_data["message"]["content"] = pruned_content
                elif isinstance(pruned_content, list):
                    replacement_data["content"] = pruned_content

                replacement = session.append(
                    "tool/result",
                    replacement_data,
                    surface_op={"op": "replace", "start": seq, "end": seq},
                    source_event_seqs=[seq],
                )

                repl_seq = replacement.get("seq") if isinstance(replacement, dict) else getattr(replacement, "seq", None)

                pruned_entries.append({
                    "original_seq": seq,
                    "originalSeq": seq,
                    "replacement_seq": repl_seq,
                    "replacementSeq": repl_seq,
                    "chars_before": chars_before,
                    "charsBefore": chars_before,
                    "chars_after": chars_after,
                    "charsAfter": chars_after,
                })

        return {
            "pruned": pruned_entries,
            "chars_removed": chars_removed_total,
            "charsRemoved": chars_removed_total,
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
        threshold_chars: Optional[int] = None,
        head_chars: Optional[int] = None,
        tail_chars: Optional[int] = None,
    ):
        super().__init__(config)
        cfg = config or {}
        self.threshold_chars = (
            threshold_chars
            if threshold_chars is not None
            else int(cfg.get("thresholdChars", cfg.get("threshold_chars", 8192)))
        )
        self.head_chars = (
            head_chars
            if head_chars is not None
            else int(cfg.get("headChars", cfg.get("head_chars", 4096)))
        )
        self.tail_chars = (
            tail_chars
            if tail_chars is not None
            else int(cfg.get("tailChars", cfg.get("tail_chars", 1024)))
        )

    def apply(self, ctx: Any) -> None:
        if not ctx.has("tool_result_pruner"):
            pruner = ToolResultPruner(
                threshold_chars=self.threshold_chars,
                head_chars=self.head_chars,
                tail_chars=self.tail_chars,
                ctx=ctx,
            )
            ctx.set_service("tool_result_pruner", pruner)
            ctx.set_service("toolResultPruner", pruner)
