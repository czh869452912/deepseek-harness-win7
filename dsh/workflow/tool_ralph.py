"""Foreground fresh-agent Ralph tool over the canonical workflow seam."""

import asyncio

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.system_prompt import FIRST_PARTY_SECTION_ORDER
from dsh.core.cancellation import subscribe_abort
from .ralph import RALPH_META, RALPH_SCRIPT, execute_ralph, read_result, render_result
from .text import js_trim
from .workflow_service import safe_integer

DESCRIPTION = ("Run a foreground fresh-agent Ralph loop toward one immutable objective. "
               "Use only when the direct human explicitly asks for Ralph or fresh-agent iteration. Each round "
               "opens a new child with no parent conversation or prior child session; the shared workspace is "
               "long-term memory, and only a bounded structured report crosses rounds. The call returns when "
               "a worker reports completion or a concrete blocker, or at the round limit. Ordinary long-running same-session work "
               "belongs to goal tools.")

OUTPUT_SCHEMA = dict(type="object", additionalProperties=False, required=["runId", "agentsStarted", "result"],
                     properties=dict(runId=dict(type="string"), agentsStarted=dict(type="integer"), result={}))


class ToolRalphPlugin(Plugin):
    id = "tool-ralph"
    name = "@deepseek-ai/dsh-tool-ralph"
    inject = ["tools", "workflowEngine", "subagents", "systemPrompt"]
    Config = Schema.object(dict(subagentProvider=Schema.string().default("spawn"),
                                maxRounds=Schema.number().default(256),
                                maxHandoffChars=Schema.number().default(16384),
                                maxResultChars=Schema.number().default(16384)))

    def apply(self, ctx, config=None):
        cfg = dict(dict(subagentProvider="spawn", maxRounds=256, maxHandoffChars=16384, maxResultChars=16384),
                   **(config if config is not None else self.config))
        provider = cfg["subagentProvider"]
        if type(provider) is not str or not provider or provider != js_trim(provider):
            raise TypeError("subagentProvider must be a non-empty normalized string")
        for key in ("maxRounds", "maxHandoffChars", "maxResultChars"):
            if not safe_integer(cfg[key]):
                raise TypeError(key + " must be a positive safe integer")
            cfg[key] = int(cfg[key])
        engine = ctx.get("workflowEngine")
        # Only this fixed, deployment-owned script has a native translation.
        if hasattr(engine, "register_native_program"):
            engine.register_native_program(RALPH_SCRIPT, execute_ralph)
        ctx.get("systemPrompt").section(dict(name="tool:ralph", order=FIRST_PARTY_SECTION_ORDER["TOOL_RALPH"],
            text="Use the ralph tool ONLY when the direct human explicitly asks for a Ralph loop or fresh-agent iterative execution. Each Ralph round starts a fresh child with no conversation seed and uses the shared workspace as durable memory. Completion and blockers are worker reports, not independent evaluation. Use same-session goal tools for ordinary long-running objectives, and plain subagents or workflows for bounded delegation and fan-out."))

        async def execute(args, execution):
            parent = execution.agent
            if parent is None:
                raise RuntimeError("Ralph tool requires a calling agent (exec.agent was undefined)")
            objective = js_trim(args["objective"])
            if not objective:
                raise ValueError("Ralph objective must be a non-empty string")
            cap = args.get("maxRounds", cfg["maxRounds"])
            if not safe_integer(cap):
                raise TypeError("Ralph maxRounds must be a positive safe integer")
            if cap > cfg["maxRounds"]:
                raise TypeError("Ralph maxRounds {} exceeds the deployment ceiling {}".format(cap, cfg["maxRounds"]))
            fresh = ctx.get("subagents").getProvider(provider)
            if fresh is None:
                raise RuntimeError('Ralph subagent provider "{}" is not registered'.format(provider))
            if not fresh.capabilities.get("outputSchema"):
                raise RuntimeError('Ralph subagent provider "{}" does not support structured output'.format(provider))
            if fresh.inheritsParentContext:
                raise RuntimeError('Ralph subagent provider "{}" inherits parent context; Ralph requires a fresh provider'.format(provider))
            run = ctx.get("workflowEngine").start(dict(script=RALPH_SCRIPT, meta=RALPH_META,
                args=dict(objective=objective, maxRounds=int(cap), maxHandoffChars=cfg["maxHandoffChars"]),
                subagentProvider=provider, maxTotalAgents=int(cap), parent=parent, signal=execution.signal))
            detach = subscribe_abort(execution.signal, lambda *_: run.cancel("parent step aborted"))
            try:
                settled = await asyncio.shield(run.result)
                reason = settled["stopReason"]
                if reason == "cancelled":
                    raise RuntimeError("Ralph workflow was cancelled" + (" (" + settled["error"] + ")" if "error" in settled else ""))
                if reason == "error":
                    raise RuntimeError("Ralph workflow failed: " + settled.get("error", "unknown error"))
                if reason != "completed":
                    raise RuntimeError("Ralph workflow ended abnormally ({})".format(reason))
                value = read_result(settled["value"], int(cap), cfg["maxHandoffChars"])
                if value["status"] == "round-failed":
                    raise RuntimeError(render_result(value, cfg["maxResultChars"]))
                return dict(runId=run.id, agentsStarted=settled["agentsStarted"], result=value)
            finally:
                detach()
                await run.dispose()

        ctx.get("tools").register(dict(name="ralph", description=DESCRIPTION,
            parameters=dict(type="object", required=["objective"], properties=dict(
                objective=dict(type="string", description="The immutable completion objective for every fresh Ralph round."),
                maxRounds=dict(type="number", description="Optional positive safe-integer round cap, bounded by the deployment ceiling."))),
            execute=execute, output=dict(schema=OUTPUT_SCHEMA,
                render=lambda args, value: [dict(type="text", text=render_result(value["result"], cfg["maxResultChars"]))]),
            presentCall=lambda args: dict(card="generic", title="ralph", rawInput=args["objective"]),
            presentResult=lambda args, result: dict(card="generic")))
