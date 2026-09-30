"""Durable surface compaction; selection is never replaced on summary failure."""
import asyncio
import uuid

from dsh.core.cancellation import aborted
from dsh.compaction.tool_pairing import tool_pairing_balanced_before, tool_pairing_balanced_after


def check_cancel(signal):
    if aborted(signal):
        raise asyncio.CancelledError("compaction cancelled")


def select(session, start, end):
    nodes = list(session.surface.nodes)
    first, last = nodes.index(start), nodes.index(end)
    if first > last:
        raise ValueError("compaction: reversed surface range")
    if not tool_pairing_balanced_before(session, start) or not tool_pairing_balanced_after(session, end):
        raise ValueError("compaction: unbalanced tool-call/result boundary")
    return nodes[first:last + 1]


def entry_state(session):
    turn, opening, seed = None, None, -1
    for event in session.events:
        kind = event["type"]
        if kind == "turn/start":
            turn = event["data"]["turn"]
        elif kind == "turn/end":
            turn = None
        elif kind == "compaction/start":
            opening = event
        elif kind == "compaction/end":
            opening = None
        elif kind == "session/end-seed":
            seed = event["seq"]
    return turn, opening if opening and opening["seq"] > seed else None


async def compact(engine, session, start, end, agent=None, signal=None,
                  manual=False, source_command_id=None, flush=None):
    from dsh.compaction.engine import ManualCompactionError
    from dsh.compaction.native_summary import frame_summary
    check_cancel(signal)
    selected = select(session, start, end)
    turn, opening = entry_state(session)
    if opening or (manual and turn is not None):
        raise ManualCompactionError("busy", "compaction: session already has active work")
    if not manual and turn is None:
        raise ValueError("automatic compaction requires an open turn")
    identity = {"compactionId": str(uuid.uuid4())}
    if source_command_id is not None:
        identity["sourceCommandId"] = source_command_id
    lifecycle = dict(identity, turn=None if manual else turn)
    opening = session.append("compaction/start", lifecycle)
    meter = engine.ctx.get("tokenMeter")
    closing, closed, failure, stage, result = False, False, None, "summary", None
    try:
        if meter is None:
            raise RuntimeError("compaction requires token_meter")
        measured = meter.measure(session)["nodes"]
        if [node["seq"] for node in measured] != list(session.surface.nodes):
            raise RuntimeError("compaction: stale token measurement")
        priced = [node for node in measured if node["seq"] in selected]
        summary = await engine.summarize(session, selected, agent, signal)
        check_cancel(signal)
        checkpoint = frame_summary(summary["summary"])
        if meter.estimate_message({"role": "user", "content": checkpoint}) >= sum(n["tokens"] for n in priced):
            raise ValueError("summary is not smaller than the shadowed content")
        current = meter.measure(session)["nodes"]
        try:
            stable = (select(session, start, end) == selected and
                      [node for node in current if node["seq"] in selected] == priced) if manual else current == measured
        except ValueError:
            stable = False
        if not stable:
            raise ManualCompactionError("changed", "compaction: selected surface changed during summarization")
        stage = "commit"
        # Shadow prices always use the fixed heuristic, independently of route image pricing.
        shadow_tokens = sum(meter.estimate_message(session.derive_event_message(session.events[seq]) or {}) for seq in selected)
        body = dict(identity, **summary, shadowedRange={"start": start, "end": end},
                    shadowedSeqs=selected, shadowedTokenCount=shadow_tokens)
        record = session.append("compaction/summary", body)
        session.append_user_message(checkpoint, surface_op={"op": "replace", "start": start, "end": end},
                                    source=dict(identity, kind="plugin", plugin="compact"),
                                    source_event_seqs=[opening["seq"], record["seq"]] + selected)
        closing = True
        end_event = session.append("compaction/end", lifecycle)
        closed = True
        result = dict(identity, startSeq=opening["seq"], endSeq=end_event["seq"], summarySeq=record["seq"],
                      summary=summary["summary"], shadowedRange=body["shadowedRange"],
                      shadowedSeqs=selected, shadowedTokenCount=shadow_tokens)
    except BaseException as error:
        failure = error
        if not closing:
            try:
                session.append("compaction/end", dict(lifecycle, error=str(error)))
                closed = True
            except Exception as close_error:
                failure, stage = close_error, "commit"
    flush_failure = None
    if closed and flush is not None:
        try:
            if not await flush():
                raise RuntimeError("no persistence listener acknowledged compaction")
        except Exception as error:
            flush_failure = error
    check_cancel(signal)
    if failure is not None:
        if manual and isinstance(failure, Exception) and not isinstance(failure, ManualCompactionError):
            raise ManualCompactionError(stage, "manual compaction failed: " + str(failure), failure)
        raise failure
    if flush_failure is not None:
        raise ManualCompactionError("persistence", "manual compaction durability checkpoint failed", flush_failure)
    return result
