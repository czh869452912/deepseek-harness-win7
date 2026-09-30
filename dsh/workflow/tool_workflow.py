"""Canonical workflow tool, presentation and contained durable run records."""

import asyncio
import logging

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.system_prompt import FIRST_PARTY_SECTION_ORDER
from dsh.core.cancellation import subscribe_abort
from .text import json_text, utf16_length, utf16_slice
from .workflow_service import render_error, safe_integer

logger = logging.getLogger(__name__)
DESCRIPTION = """Run a JavaScript workflow script that orchestrates subagents at scale. Use this for work that fans out across many independent pieces — an audit over many files, a migration, multi-angle research, adversarial verification of findings — where you write the orchestration as a script instead of delegating turn by turn.

The workflow's identity rides the `meta` parameter as JSON: required `name` (short kebab-case) and `description` strings, optional `whenToUse` string and `phases` array (`{title, detail?, provider?, model?}`). The `script` parameter is the plain JavaScript body ONLY (NOT TypeScript, and NO `export const meta` statement — meta is a parameter, not code), running with top-level await; end with `return <value>` — the value must be JSON-serializable and is this tool's result.

Script-body hooks:
- `agent(prompt, opts?): Promise<any>` — run one subagent to completion. Without `opts.schema` it resolves to the child's final text; with `opts.schema` (an object-rooted JSON Schema using ONLY type/properties/required/additionalProperties/items/enum/const/oneOf — no pattern/format/numeric bounds) it resolves to the validated object. Resolves `null` when the child fails (filter with `.filter(Boolean)`). Other opts: `label` (display), `phase` (progress group), and independent `provider`/`model` LLM target overrides (either may be provided alone). Anything else (`effort`/`isolation`/`agentType`) is rejected loudly.
- `pipeline(items, ...stages): Promise<any[]>` — run each item through the stages independently with NO barrier between stages (prefer this for multi-stage work). Each stage receives `(prev, item, index)`. An ordinary stage throw drops that ITEM to `null` and skips its remaining stages.
- `parallel(thunks): Promise<any[]>` — run zero-argument functions concurrently and await ALL of them (a barrier; use only when a stage genuinely needs every prior result together). A throwing thunk resolves to `null`.
- `phase(title)` — start a progress phase; `log(message)` — narrate progress; `args` — the tool call's `args` input, verbatim.

Misused hooks (bad arguments, unknown options, unsupported schemas, tripped caps) throw errors that ALWAYS kill the script — they never dissolve into a per-item `null`.

Constraints: concurrency and total-agent caps apply; no filesystem, network, timers, or Node.js APIs are provided — the agents do the work, the script only coordinates them. The run executes in the foreground: this call returns when the whole script finishes."""

OUTPUT_SCHEMA = dict(type="object", additionalProperties=False, required=["runId", "agentsStarted", "result"],
                     properties=dict(runId=dict(type="string"), agentsStarted=dict(type="integer"), result={}))
META_SCHEMA = dict(type="object", additionalProperties=True, required=["name", "description"], properties=dict(
    name=dict(type="string", description="Short kebab-case workflow name."),
    description=dict(type="string", description="One-line description of what the workflow does."),
    whenToUse=dict(type="string", description="Optional guidance on when this workflow applies."),
    phases=dict(type="array", description="Optional phase declarations matched by phase() calls.", items=dict(
        type="object", additionalProperties=True, required=["title"], properties=dict(
            title=dict(type="string", description="The phase title phase() calls match by exact string."),
            detail=dict(type="string", description="Optional one-line description of the phase."),
            provider=dict(type="string", description="Optional provider override this phase is expected to use."),
            model=dict(type="string", description="Optional model override this phase is expected to use."))))))


class WorkflowRecorder:
    def __init__(self, ctx):
        self.active = {}
        ctx.on("workflow/agent-start", self.agent_start)
        ctx.on("workflow/agent-end", self.agent_end)

    def append(self, session, event, data):
        try:
            session.append(event, data)
            return True
        except Exception as error:
            logger.warning("tool-workflow: disabled durable record after %s append failed: %s", event, render_error(error))
            return False

    def start(self, session, run):
        if self.append(session, "tool-workflow/run-start", dict(runId=run.id, name=run.meta["name"])):
            self.active[run.id] = session

    def agent_start(self, info, agent):
        session = self.active.get(info["id"])
        if session is not None:
            data = dict(runId=info["id"], seq=agent["seq"], label=agent["label"], childId=agent["childId"])
            if "phase" in agent:
                data["phase"] = agent["phase"]
            if not self.append(session, "tool-workflow/agent-start", data):
                self.active.pop(info["id"], None)

    def agent_end(self, info, agent):
        session = self.active.get(info["id"])
        if session is not None and not self.append(session, "tool-workflow/agent-end", dict(runId=info["id"], seq=agent["seq"], outcome=agent["outcome"])):
            self.active.pop(info["id"], None)

    def finish(self, run_id, stop_reason):
        session = self.active.pop(run_id, None)
        if session is not None:
            self.append(session, "tool-workflow/run-end", dict(runId=run_id, stopReason=stop_reason))


def render_result(name, agents_started, value, max_chars):
    rendered = json_text(value, True)
    if utf16_length(rendered) > max_chars:
        rendered = utf16_slice(rendered, max_chars) + "\n\u2026 [truncated: {} more characters]".format(utf16_length(rendered) - max_chars)
    return 'workflow "{}" completed ({} agent{}).\nReturn value:\n{}'.format(name, agents_started, "" if agents_started == 1 else "s", rendered)


class ToolWorkflowPlugin(Plugin):
    id = "tool-workflow"
    name = "@deepseek-ai/dsh-tool-workflow"
    inject = ["tools", "workflowEngine", "systemPrompt"]
    Config = Schema.object(dict(toolName=Schema.string().default("workflow"), maxResultChars=Schema.number().default(50000)))

    def apply(self, ctx, config=None):
        cfg = dict(dict(toolName="workflow", maxResultChars=50000), **(config if config is not None else self.config))
        name, cap = cfg["toolName"], cfg["maxResultChars"]
        if type(name) is not str or not name:
            raise TypeError("workflow toolName must be a non-empty string")
        if not safe_integer(cap):
            raise TypeError("workflow maxResultChars must be a positive safe integer")
        cap = int(cap)
        recorder = WorkflowRecorder(ctx)
        ctx.get("systemPrompt").section(dict(name="tool:" + name, order=FIRST_PARTY_SECTION_ORDER["TOOL_WORKFLOW"],
            text="Use the " + name + " tool ONLY when the user explicitly asks for a workflow or for large multi-agent orchestration: you write a JavaScript script (the tool description documents the exact format) that fans work out across many subagents with phases and structured results. For one or two delegations, prefer plain subagent calls."))

        async def execute(args, execution):
            parent = execution.agent
            if parent is None:
                raise RuntimeError("workflow tool requires a calling agent (exec.agent was undefined)")
            request = dict(script=args["script"], meta=args["meta"], parent=parent, signal=execution.signal)
            if "args" in args:
                request["args"] = args["args"]
            run = ctx.get("workflowEngine").start(request)
            records = execution.parent is None
            if records:
                recorder.start(parent.session, run)
            detach = subscribe_abort(execution.signal, lambda *_: run.cancel("parent step aborted"))
            result = None
            try:
                result = await asyncio.shield(run.result)
                reason = result["stopReason"]
                if reason == "cancelled":
                    raise RuntimeError("workflow run was cancelled" + (" (" + result["error"] + ")" if "error" in result else ""))
                if reason == "error":
                    raise RuntimeError("workflow run failed: " + result.get("error", "unknown error"))
                if reason != "completed":
                    raise RuntimeError("workflow run ended abnormally ({})".format(reason))
                return dict(runId=run.id, agentsStarted=result["agentsStarted"], result=result["value"])
            finally:
                detach()
                try:
                    await run.dispose()
                    if records and result is not None:
                        recorder.finish(run.id, result["stopReason"])
                finally:
                    recorder.active.pop(run.id, None)

        ctx.get("tools").register(dict(name=name, description=DESCRIPTION,
            parameters=dict(type="object", required=["script", "meta"], properties=dict(
                script=dict(type="string", description="The plain-JS workflow script body (top-level await allowed; NO `export const meta` statement; end with `return <json-value>`)."),
                meta=dict(META_SCHEMA, description="The workflow identity block (plain JSON \u2014 never code)."),
                args=dict(type="object", additionalProperties=True,
                    description='Optional JSON input exposed to the script as the `args` global (wrap a bare list as a field, e.g. {"files": [...]}).'))),
            execute=execute, output=dict(schema=OUTPUT_SCHEMA, render=lambda args, value: [dict(type="text",
                text=render_result(args["meta"]["name"], value["agentsStarted"], value["result"], cap))]),
            presentCall=lambda args: dict(card="generic", title="workflow: " + args["meta"]["name"], rawInput=args["script"]),
            presentResult=lambda args, result: dict(card="generic")))
