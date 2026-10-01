"""
Manual compaction command plugin (`@deepseek-ai/dsh-command-compact`).
Registers the `/compact` command to force immediate conversation summarization
through the backend-independent compaction seam, matching
reference/packages/compaction/command-compact/src/index.ts.
"""

import asyncio
from typing import Any, Dict
from dsh.compaction.engine import ManualCompactionError
from dsh.cordis.plugin import Plugin
from dsh.cordis.utils import _V8_WHITESPACE_OR_LINE_TERMINATOR
from dsh.core.cancellation import aborted


FAILURES = {
    "busy": "Compaction is unavailable because this process has an active compaction, or the agent is not idle.",
    "cancelled": "Compaction cancelled.",
    "changed": "The history selected for compaction changed before it could be replaced. The conversation is unchanged; the attempt is recorded in the session log.",
    "summary": "Compaction could not produce a useful summary. The conversation is unchanged; the attempt is recorded in the session log.",
    "commit": "Compaction did not finish cleanly; some session history may have changed. Inspect the current session state before retrying.",
    "persistence": "Compaction finished, but the session could not be saved.",
}


class CommandCompactPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-command-compact`: Registers the `/compact` command.
    """

    id = "command-compact"
    name = "@deepseek-ai/dsh-command-compact"
    inject = ["commands", "compaction"]

    def apply(self, ctx: Any) -> None:
        active = set()

        async def exec_compact(invocation: Any) -> Dict[str, Any]:
            if any(ord(char) not in _V8_WHITESPACE_OR_LINE_TERMINATOR for char in invocation.raw_input):
                return {"kind": "error", "text": "Usage: /compact (no arguments)"}
            try:
                result = await ctx.get("compaction").compact_now(invocation.agent, invocation.signal, invocation.command_id)
                if result is None:
                    return {"kind": "success", "text": "No compactable history yet."}
                return {"kind": "success",
                        "text": "Compacted {} history items (~{} tokens).".format(
                            len(result["shadowedSeqs"]), result["shadowedTokenCount"]),
                        "sourceEventSeq": result["summarySeq"]}
            except (Exception, asyncio.CancelledError) as error:
                if aborted(invocation.signal):
                    return {"kind": "error", "text": "Compaction cancelled."}
                if isinstance(error, ManualCompactionError):
                    if error.code not in FAILURES:
                        raise TypeError("unknown manual compaction error code: " + str(error.code)) from error
                    return {"kind": "error", "text": FAILURES[error.code]}
                raise

        def handler(invocation):
            operation = asyncio.create_task(exec_compact(invocation))
            active.add(operation)
            def retire(task):
                active.discard(task)
                if not task.cancelled():
                    task.exception()
            operation.add_done_callback(retire)
            return operation

        async def drain():
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(active)), return_exceptions=True)

        def lifecycle():
            # Composite cleanup is LIFO: unregister before awaiting active calls.
            yield drain
            yield ctx.get("commands").register({
                "name": "compact", "description": "Compact older conversation history", "handler": handler,
            })
        ctx.effect(lifecycle, "command-compact lifecycle")
