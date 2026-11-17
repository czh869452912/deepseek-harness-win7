"""Durable surface compaction; selection is never replaced on summary failure."""
import asyncio
import uuid

from dsh.core.abort import abort_reason_error
from dsh.core.cancellation import aborted
from dsh.llm.error import error_chain
from dsh.llm.message import create_user_message
from dsh.compaction.tool_pairing import tool_pairing_balanced_before, tool_pairing_balanced_after


def check_cancel(signal):
    if aborted(signal):
        reason = getattr(signal, "reason", None)
        if isinstance(reason, BaseException):
            raise reason
        if not isinstance(signal, asyncio.Event):
            raise abort_reason_error(signal, "compaction cancelled")
        # A native business abort is an ordinary failure. CancelledError marks
        # an asyncio Task cancelled; shield then loses its attached reason.
        # Keep that historical spelling only for explicit Event adapters.
        error = (asyncio.CancelledError if isinstance(signal, asyncio.Event) else RuntimeError)("compaction cancelled")
        error.reason = reason
        raise error


class SurfaceChangedError(RuntimeError):
    pass


def summarization_input(session, selected):
    header = session.request_header() or {}
    messages = [session.derive_event_message(session.events[seq]) for seq in selected]
    result = {"messages": [message for message in messages if message is not None]}
    for key in ("system", "tools"):
        if key in header:
            result[key] = header[key]
    return result


def select(session, start, end):
    nodes = list(session.surface.nodes)
    if start not in nodes:
        raise ValueError('compactRegion: start seq %s not found in surface' % start)
    if end not in nodes:
        raise ValueError('compactRegion: end seq %s not found in surface' % end)
    first, last = nodes.index(start), nodes.index(end)
    if first > last:
        raise ValueError('compactRegion: start seq %s (position %s) is after end seq %s (position %s) on the surface' % (start, first, end, last))
    if not tool_pairing_balanced_before(session, start):
        raise ValueError("compactRegion: start seq %s is not a balanced boundary (would split a step's tool-call/result pair)" % start)
    if not tool_pairing_balanced_after(session, end):
        raise ValueError('compactRegion: end seq %s is not a balanced boundary (would split a step, or the step is still open)' % end)
    return nodes[first:last + 1]


def prepare(session, meter, start, end, selected):
    measured = meter.measure(session)['nodes']
    nodes = list(session.surface.nodes)
    first, last = nodes.index(start), nodes.index(end)
    priced = measured[first:last + 1]
    if [node['seq'] for node in priced] != selected:
        raise SurfaceChangedError('compaction: selected surface changed before summarization began')
    return measured, priced, sum(node['heuristicTokens'] for node in priced)


def assert_stable(session, meter, start, end, selected, measured, priced, manual):
    if not manual:
        if meter.measure(session)['nodes'] != measured:
            raise SurfaceChangedError('compaction: session surface changed during summarization')
        return
    try:
        current = select(session, start, end)
    except ValueError as error:
        raise SurfaceChangedError('compaction: the selected span is no longer a valid replacement target') from error
    if current != selected:
        raise SurfaceChangedError('compaction: the selected span changed during summarization')
    nodes = list(session.surface.nodes)
    current = meter.measure(session)['nodes'][nodes.index(start):nodes.index(end) + 1]
    if current != priced:
        raise SurfaceChangedError('compaction: the selected span was rewritten during summarization')


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
    if manual:
        check_cancel(signal)
    selected = select(session, start, end)
    turn, opening = entry_state(session)
    if opening:
        raise ManualCompactionError('busy', 'compaction: compaction already in progress; the session compaction lock is already active')
    if manual and turn is not None:
        raise ManualCompactionError('busy', 'manual compaction: the session already has an open turn')
    if not manual and turn is None:
        raise ValueError('compactRegion: no open turn — automatic compaction events must be enclosed in a turn')
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
        measured, priced, shadow_tokens = prepare(session, meter, start, end, selected)
        while True:
            check_cancel(signal)
            try:
                summary = await engine.summarize(engine.summarization_input(session, selected), agent, signal)
                break
            except Exception as error:
                recover = getattr(engine, 'recover_summary', None)
                if aborted(signal) or recover is None:
                    raise
                assert_stable(session, meter, start, end, selected, measured, priced, manual)
                if not await recover(error, agent, selected, signal):
                    raise
                selected = select(session, start, end)
                measured, priced, shadow_tokens = prepare(session, meter, start, end, selected)
        checkpoint = frame_summary(summary["summary"])
        source = (dict(identity, kind='compact-checkpoint') if getattr(session, 'format_version', 3) == 4
            else dict(identity, kind='plugin', plugin='compact'))
        checkpoint_message = create_user_message(dict(content=checkpoint, source=source))
        estimate, route_tokens = meter.estimate_message(checkpoint_message), sum(n['tokens'] for n in priced)
        if estimate >= route_tokens:
            raise ValueError('summary is not smaller than the shadowed content (%s estimated framed tokens >= %s)' % (estimate, route_tokens))
        if manual:
            check_cancel(signal)
        assert_stable(session, meter, start, end, selected, measured, priced, manual)
        stage = "commit"
        body = dict(identity, summary=summary["summary"], provider=summary["provider"], model=summary["model"],
                    shadowedRange={"start": start, "end": end}, shadowedSeqs=selected,
                    shadowedTokenCount=shadow_tokens)
        for key in ("rawOutput", "maxTokens", "usage"):
            if key in summary:
                body[key] = summary[key]
        if summary.get("llmStreamCall") is True:
            body["llmStreamCall"] = True
        record = session.append("compaction/summary", body)
        session.append("user/message", checkpoint_message, surface_op=engine.replacement_surface(start, end),
                       source_event_seqs=[opening["seq"], record["seq"]] + selected)
        closing = True
        end_event = session.append("compaction/end", lifecycle)
        closed = True
        result = dict(identity, startSeq=opening["seq"], endSeq=end_event["seq"], summarySeq=record["seq"],
                      summary=summary["summary"], shadowedRange=body["shadowedRange"],
                      shadowedSeqs=selected, shadowedTokenCount=shadow_tokens)
    except BaseException as error:
        failure = error
        if closing:
            stage = "commit"
        if not closing:
            closing = True
            try:
                session.append("compaction/end", dict(lifecycle, error=error_chain(error)))
                closed = True
            except Exception as close_error:
                failure, stage = close_error, "commit"
    flush_failure = None
    if closed and flush is not None:
        try:
            await flush()
        except Exception as error:
            flush_failure = error
    if manual:
        check_cancel(signal)
    if failure is not None:
        if manual:
            code = "commit" if stage == "commit" else "changed" if isinstance(failure, SurfaceChangedError) else "summary"
            message = {"commit": "manual compaction did not commit cleanly",
                       "changed": "the compacted history changed during manual compaction",
                       "summary": "manual compaction could not produce a smaller summary"}[code]
            raise ManualCompactionError(code, message, failure) from failure
        raise failure
    if flush_failure is not None:
        raise ManualCompactionError("persistence", "manual compaction durability checkpoint failed", flush_failure)
    return result
