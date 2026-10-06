"""Auxiliary summarization through the mounted LLM, using the routed prefix."""
from dsh.core.cancellation import aborted
from dsh.llm.stream_bridge import iter_chunks
from dsh.llm.image_content import images
from dsh.cordis.utils import _V8_WHITESPACE_OR_LINE_TERMINATOR

INSTRUCTION = """You are now acting as a compaction engine for this AI coding assistant. Condense the conversation ABOVE into a structured checkpoint that lets another model resume the work with no loss of essential context.

Output EXACTLY the Markdown structure below: keep every section, in order. Use terse bullets, not prose paragraphs. Write "(none)" for an empty section — never drop a section.

## Primary Request and Intent
- [the user's original and evolving goals; quote verbatim where the exact wording matters]

## Key Technical Concepts
- [technologies, frameworks, patterns, and conventions in play]

## Files and Code
- [exact path: why it matters, key changes or snippets]

## Errors and Fixes
- [error: how it was resolved, plus any related user feedback]

## Pending Jobs
- [explicitly requested work not yet completed]

## Current Work
- [precisely what was in progress at this checkpoint]

## Next Step
- [the single next action, directly in line with the most recent request, or "(none)"]

## Critical Context
- [decisions and their rationale, constraints, user preferences, open questions, data needed to continue]

Rules:
- Write concise English engineering prose. Preserve exact file paths, commands, error strings, identifiers, numeric values, function signatures, and syntax fragments.
- Capture user feedback and explicit instructions faithfully, especially corrections.
- Do NOT mention this summarization request or that the context was compacted.
- Output only the checkpoint text: do not call any tool or take any other action.
- If the conversation already contains a <compacted-summary> block, it is a PRIOR checkpoint. Do not copy it forward verbatim: preserve still-true facts, drop stale ones, and merge newer information into a single consolidated summary under the same structure."""

PREAMBLE = ('This is an automatically generated checkpoint condensing an earlier span of the conversation to free up context. '
            'Treat the captured context as established background and build on it without restating it. '
            'Continue the task directly from the messages that follow, without acknowledging this checkpoint.')


def frame_summary(summary):
    return [{"type": "text", "text": PREAMBLE + "\n\n<compacted-summary>"}] + summary + [
        {"type": "text", "text": "</compacted-summary>"}]


async def summarize(engine, input, agent, signal):
    from dsh.core.agent_loop import BlockAssembler
    from dsh.llm.llm_service import LlmError
    from dsh.compaction.compaction_basic.config import resolve_target_policy
    from dsh.compaction.engine import conversation_target
    session = agent.session
    policy_target = conversation_target(agent)
    cfg = engine.config if not policy_target else resolve_target_policy(engine.config, policy_target)
    header = session.request_header() or {}
    options = getattr(agent, "options", None)
    target = ({"provider": cfg["summarizationProvider"], "model": cfg["summarizationModel"]}
              if cfg["summarizationProvider"] else header.get("config"))
    target = target or {"provider": getattr(options, "provider", None), "model": getattr(options, "model", None)}
    if not target.get("provider") or not target.get("model"):
        raise ValueError("no provider/model available for summarization")
    messages = list(input["messages"])
    messages.append({"role": "user", "content": [{"type": "text", "text": INSTRUCTION}],
                     "source": {"kind": "plugin", "plugin": "dsh-compaction-basic"}})
    request = dict(provider=target["provider"], model=target["model"], messages=messages,
                   maxTokens=cfg["maxTokens"], sessionId=session.id, purpose="compaction", signal=signal)
    for key in ("system", "tools"):
        if key in input:
            request[key] = input[key]
    assembler = BlockAssembler()
    reader = iter_chunks(engine.ctx.get("llm").stream(request), lambda: aborted(signal))
    try:
        async for chunk in reader:
            assembler.push(chunk)
    finally:
        await reader.aclose()
    finish = assembler.finish
    if finish["kind"] in ("error", "aborted"):
        failure = finish.get("failure") or {}
        error = RuntimeError(failure.get("message", "summarization did not complete"))
        error.name = 'Error'
        error.message = str(error)
        error.code = failure.get('code', 'UNKNOWN')
        raise error
    if finish["kind"] == "max-tokens":
        raise LlmError("summarization truncated at the token cap", "MAX_TOKENS")
    raw = assembler.blocks()
    if any(images(raw)):
        raise LlmError("compaction summary cannot contain image output", "UNSUPPORTED_CONTENT")
    summary = [block for block in raw if block.get("type") == "text"]
    if not any(any(ord(char) not in _V8_WHITESPACE_OR_LINE_TERMINATOR for char in block.get("text", "")) for block in summary):
        raise ValueError("summarization produced no text summary content")
    result = dict(summary=summary, rawOutput=raw, llmStreamCall=True,
                  provider=request["provider"], model=request["model"], maxTokens=cfg["maxTokens"])
    if assembler.usage is not None:
        result["usage"] = assembler.usage
    return result
