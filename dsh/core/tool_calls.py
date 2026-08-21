"""
Schedules one assistant step's tool calls. Exclusive calls form barriers;
parallel calls use a bounded rolling pool and are reclassified before start.
Dispatch may overlap, while policy, results, and result context remain
model-ordered. Abort records synthetic error results for skipped calls.
Aligned 1:1 with official `@deepseek-ai/dsh-agent-loop/tool-calls`.
"""

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional
from dsh.core.tools import (
    TOOL_ABORTED_BEFORE_DISPATCH,
    ToolExecutionInput,
    ToolExecutionResult,
)


class PlannedCall:
    def __init__(self, block: Dict[str, Any], exec_input: ToolExecutionInput):
        self.block = block
        self.exec = exec_input


class Slot:
    def __init__(self, exec_input: ToolExecutionInput, result: ToolExecutionResult, needs_post: bool):
        self.exec = exec_input
        self.result = result
        self.needs_post = needs_post


class GroupOutcome:
    def __init__(self, consumed: int, aborted: bool, concluded: bool):
        self.consumed = consumed
        self.aborted = aborted
        self.concluded = concluded


def parse_arguments(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return raw


async def execute_tool_calls(
    ctx: Any,
    agent: Any,
    turn: int,
    step: int,
    tool_calls: List[Dict[str, Any]],
    signal: Optional[asyncio.Event] = None,
    accept_context: Optional[Callable[[Any], None]] = None,
    max_parallel: int = 8,
) -> Dict[str, bool]:
    session = agent.session
    tools_service = ctx.get("tools")

    planned: List[PlannedCall] = []
    for block in tool_calls:
        call_id = block.get("id") or block.get("call_id") or ""
        func = block.get("function", {}) if "function" in block else block
        name = func.get("name") or block.get("name", "")
        args_raw = func.get("arguments") or block.get("arguments", "{}")
        args = parse_arguments(args_raw)

        exec_input = ToolExecutionInput(
            call_id=call_id,
            name=name,
            arguments=args,
            agent=agent,
            signal=signal,
        )
        planned.append(PlannedCall(block=block, exec_input=exec_input))

    next_idx = 0
    concluded = False

    while next_idx < len(planned):
        first = planned[next_idx]
        mode = "parallel"
        if tools_service:
            mode = tools_service.execution_mode(first.exec).get("kind", "parallel")

        group = planned[next_idx:] if mode == "parallel" else [first]
        outcome = await run_group(
            ctx=ctx,
            agent=agent,
            turn=turn,
            step=step,
            group=group,
            mode=mode,
            signal=signal,
            accept_context=accept_context,
            max_parallel=max_parallel,
        )

        next_idx += outcome.consumed
        concluded = concluded or outcome.concluded

        if outcome.aborted:
            for call in planned[next_idx:]:
                append_skipped_tool_call(session, turn, step, call.block)
            return {"concluded": concluded}

    return {"concluded": concluded}


async def run_group(
    ctx: Any,
    agent: Any,
    turn: int,
    step: int,
    group: List[PlannedCall],
    mode: str,
    signal: Optional[asyncio.Event],
    accept_context: Optional[Callable[[Any], None]],
    max_parallel: int,
) -> GroupOutcome:
    session = agent.session
    tools_service = ctx.get("tools")
    slots: List[Optional[Slot]] = [None] * len(group)
    call_seqs: List[int] = [-1] * len(group)

    next_to_start = 0
    committed = 0
    started = 0
    aborted = signal.is_set() if signal else False
    concluded = False
    scheduler_failure: Optional[Exception] = None

    async def commit_ready() -> None:
        nonlocal committed, concluded
        while committed < len(group):
            slot = slots[committed]
            if slot is None:
                break
            call = group[committed]
            result = slot.result
            if tools_service and slot.needs_post:
                result = await tools_service.finalize(slot.exec, slot.result)

            append_tool_result(session, turn, step, call.block, result, call_seqs[committed])
            if accept_context and result.additional_contexts:
                for ctx_item in result.additional_contexts:
                    accept_context(ctx_item)
            if result.concludes_turn:
                concluded = True
            committed += 1

    in_flight: Dict[int, asyncio.Task] = {}

    async def start_call(index: int) -> None:
        nonlocal started, scheduler_failure
        call = group[index]
        call_seqs[index] = append_tool_call(session, turn, step, call.block)
        started += 1

        if not tools_service:
            err = ToolExecutionResult.from_raw("Error: Tools service unavailable", is_error=True)
            slots[index] = Slot(exec_input=call.exec, result=err, needs_post=False)
            return

        try:
            prep = await tools_service.prepare(call.exec)
        except Exception as e:
            scheduler_failure = e
            return

        async def _dispatch_task(idx: int, exec_inp: ToolExecutionInput) -> int:
            nonlocal scheduler_failure
            try:
                outcome = await tools_service.dispatch(exec_inp)
                slots[idx] = Slot(
                    exec_input=exec_inp,
                    result=outcome.get("result"),
                    needs_post=(outcome.get("kind") == "post-result"),
                )
            except Exception as e:
                scheduler_failure = e
            return idx

        task = asyncio.create_task(_dispatch_task(index, prep.get("exec", call.exec)))
        in_flight[index] = task

    async def fill_pool() -> None:
        nonlocal next_to_start, aborted
        while (
            not aborted
            and next_to_start < len(group)
            and len(in_flight) < max_parallel
        ):
            next_call = group[next_to_start]
            if (
                next_to_start > 0
                and mode == "parallel"
                and tools_service
                and tools_service.execution_mode(next_call.exec).get("kind") != "parallel"
            ):
                break

            await start_call(next_to_start)
            next_to_start += 1
            if scheduler_failure:
                raise scheduler_failure
            await commit_ready()
            if scheduler_failure:
                raise scheduler_failure
            if signal and signal.is_set():
                aborted = True

    try:
        await fill_pool()
        while in_flight:
            done, _ = await asyncio.wait(in_flight.values(), return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                # Find finished index
                for k, v in list(in_flight.items()):
                    if v == d:
                        del in_flight[k]
                        break
            if scheduler_failure:
                raise scheduler_failure
            await commit_ready()
            if scheduler_failure:
                raise scheduler_failure
            if signal and signal.is_set():
                aborted = True
            await fill_pool()
    except Exception as err:
        scheduler_failure = err
        if in_flight:
            await asyncio.gather(*in_flight.values(), return_exceptions=True)
        raise err

    if aborted:
        for call in group[started:]:
            append_skipped_tool_call(session, turn, step, call.block)
        return GroupOutcome(consumed=len(group), aborted=True, concluded=concluded)

    return GroupOutcome(consumed=started, aborted=False, concluded=concluded)


def append_skipped_tool_call(session: Any, turn: int, step: int, block: Dict[str, Any]) -> None:
    call_seq = append_tool_call(session, turn, step, block)
    append_tool_result(
        session,
        turn,
        step,
        block,
        ToolExecutionResult(
            content=[{"type": "text", "text": "Error: tool call aborted before dispatch"}],
            is_error=True,
            error={"name": "AbortError", "code": TOOL_ABORTED_BEFORE_DISPATCH, "message": "tool call aborted before dispatch"},
        ),
        call_seq,
    )


def append_tool_call(session: Any, turn: int, step: int, block: Dict[str, Any]) -> int:
    call_id = block.get("id") or block.get("call_id") or ""
    func = block.get("function", {}) if "function" in block else block
    name = func.get("name") or block.get("name", "")
    args = func.get("arguments") or block.get("arguments", "{}")

    ev = session.append(
        "tool/call",
        {"turn": turn, "step": step, "callId": call_id, "name": name, "arguments": args},
    )
    return getattr(ev, "seq", getattr(ev, "get", lambda k, d=0: d)("seq", 0)) if isinstance(ev, dict) else getattr(ev, "seq", 0)


def append_tool_result(
    session: Any,
    turn: int,
    step: int,
    block: Dict[str, Any],
    result: ToolExecutionResult,
    call_seq: int,
) -> None:
    call_id = block.get("id") or block.get("call_id") or ""
    func = block.get("function", {}) if "function" in block else block
    name = func.get("name") or block.get("name", "")
    text_content = "".join(b.get("text", "") for b in result.content if b.get("type") == "text")

    session.append_tool_result(
        tool_call_id=call_id,
        name=name,
        result=text_content,
        turn=turn,
        step=step,
        error=result.error if result.is_error else None,
        timing={"durationMs": 0},
    )
