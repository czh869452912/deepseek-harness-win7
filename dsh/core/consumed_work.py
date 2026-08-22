"""
How one agent log accounts for the work it consumed.
Aligned 1:1 with official `@deepseek-ai/dsh-agent/consumed-work`.
"""

from typing import Any, Dict, List, Optional, Set


class ConsumedWork:
    """How one agent log accounts for the work it consumed."""

    def __init__(self, end: Optional[Dict[str, Any]] = None, dropped_unrun: bool = False):
        self.end = end
        self.dropped_unrun = dropped_unrun

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"droppedUnrun": self.dropped_unrun}
        if self.end is not None:
            res["end"] = self.end
        return res


def accounts_for_claim(reason: Dict[str, Any]) -> bool:
    kind = reason.get("kind") if isinstance(reason, dict) else None
    if kind == "completed":
        return False
    # blocked, aborted, interrupted, error, or custom kinds
    return True


def fold_consumed_work(events: List[Dict[str, Any]]) -> ConsumedWork:
    """
    Fold one agent log into its account of consumed work.
    """
    stepped: Set[int] = set()
    claimed: Set[int] = set()
    open_turn: Optional[int] = None
    end: Optional[Dict[str, Any]] = None
    dropped_unrun: bool = False

    for event in events:
        etype = event.get("type")
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}

        if etype == "turn/start":
            open_turn = data.get("turn")
        elif etype == "step/start":
            t = data.get("turn")
            if t is not None:
                stepped.add(t)
        elif etype == "agent/inbox/spliced":
            removed_count = data.get("removedCount", data.get("removed_count"))
            inserted = data.get("inserted", [])
            outcome = data.get("outcome")

            if removed_count is not None:
                if outcome == "canceled":
                    if len(inserted) == 0:
                        dropped_unrun = True
                elif open_turn is not None:
                    claimed.add(open_turn)
        elif etype == "turn/end":
            turn = data.get("turn")
            reason = data.get("reason", {})
            open_turn = None

            is_stepped = turn in stepped
            if is_stepped:
                stepped.discard(turn)
            is_claimed = turn in claimed
            if is_claimed:
                claimed.discard(turn)

            if is_stepped or (is_claimed and accounts_for_claim(reason)):
                end = event
                dropped_unrun = False

    return ConsumedWork(end=end, dropped_unrun=dropped_unrun)
