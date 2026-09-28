"""Canonical model-facing controls over the scoped jobs provider."""
import math
import weakref

from dsh.cordis.plugin import Plugin
from dsh.llm.message import create_user_message


SYSTEM_PROMPT_JOBS_TEXT = (
    "Track every background job id you start. You are notified in-session when a job finishes — "
    "do not busy-poll or sleep on one; keep working on independent steps and do not duplicate a running job's work. "
    "Before giving a final answer, collect every still-relevant job with job_output "
    "(set wait: true only when you are genuinely blocked on it), and job_kill jobs that stopped mattering."
)


PUBLIC_FIELDS = ("id", "kind", "label", "status", "detail", "startedAt", "finishedAt")
PUBLIC_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": dict({key: {"type": "string"} for key in PUBLIC_FIELDS[:5]},
                       startedAt={"type": "integer"}, finishedAt={"type": "integer"}),
    "required": ["id", "kind", "label", "status", "startedAt"],
}
PUBLIC_SCHEMA["properties"]["status"]["enum"] = ["running", "stopping", "completed", "killed", "failed"]


def public_job(snapshot):
    return {key: snapshot[key] for key in PUBLIC_FIELDS if key in snapshot}


def status_line(snapshot):
    return "[status: " + snapshot["status"] + (", " + snapshot["detail"] if "detail" in snapshot else "") + "]"


def tail(text, maximum):
    return text.encode("utf-8")[-maximum:].decode("utf-8", errors="ignore") if maximum > 0 else ""


def fit(content, suffix, maximum, omitted):
    complete = content + suffix
    if maximum is None or len(complete.encode("utf-8")) <= maximum:
        return complete
    fixed = ("" if content.endswith(omitted.lstrip()) else omitted) + suffix
    room = maximum - len(fixed.encode("utf-8"))
    return tail(fixed, maximum) if room <= 0 else tail(content, room) + fixed


def blocks(text):
    return [{"type": "text", "text": text}]


def completion_notice(snapshot):
    prefix = "background job " + snapshot["id"]
    detail = " ({}: {}) finished {}".format(snapshot["kind"], snapshot["label"], status_line(snapshot))
    action, omitted = "\nDone; job_output.", "\n[notice truncated]"
    complete = prefix + detail + ". Read its output with job_output."
    maximum = snapshot.get("outputLimitBytes")
    if maximum is None or len(complete.encode("utf-8")) <= maximum:
        return complete
    fixed = prefix + omitted + action
    room = maximum - len(fixed.encode("utf-8"))
    if room >= 0:
        return prefix + detail.encode("utf-8")[:room].decode("utf-8", errors="ignore") + omitted + action
    compact = prefix + action
    if len(compact.encode("utf-8")) <= maximum:
        return compact
    room = maximum - len(action.encode("utf-8"))
    return tail(action, maximum) if room <= 0 else prefix.encode("utf-8")[:room].decode("utf-8", errors="ignore") + action


class ToolJobsPlugin(Plugin):
    id = "tool-jobs"
    name = "@deepseek-ai/dsh-tool-jobs"
    inject = ["tools", "jobs", "systemPrompt"]

    def apply(self, ctx):
        jobs = ctx.get("jobs")
        config = self.config or {}
        default, cap = config.get("waitTimeoutMs", 30000), config.get("maxWaitTimeoutMs", 600000)
        for value in (default, cap):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 1:
                raise ValueError("tool-jobs: wait timeouts must be finite and at least 1ms")
        if default > cap:
            raise ValueError("tool-jobs: waitTimeoutMs exceeds maxWaitTimeoutMs")
        delivery, budget = config.get("completionDelivery", "wakeup"), config.get("maxConsecutiveWakes", 3)
        if delivery not in ("wakeup", "quiet") or type(budget) is not int or not 1 <= budget <= 9007199254740991:
            raise ValueError("invalid tool-jobs completion delivery or wake budget")
        spent, limits = weakref.WeakKeyDictionary(), {}

        def claimed(payload):
            if payload.get("message", {}).get("source", {}).get("kind") == "user":
                spent.pop(payload["agent"], None)
        if delivery == "wakeup":
            ctx.on("agent/inbox/claimed", claimed)

        def visible_limit(execution):
            if execution.name not in ("job_output", "job_kill"):
                return None
            for snapshot in jobs.list(execution.agent):
                if snapshot["id"] == execution.arguments.get("job_id"):
                    return snapshot.get("outputLimitBytes")
            return None

        async def pre_execute(execution, next_fn):
            maximum = visible_limit(execution)
            if maximum is not None:
                limits[id(execution)] = maximum
            return await next_fn()
        ctx.on("tools/pre-execute", pre_execute, {"prepend": True})

        def finalize(execution, result):
            maximum = limits.pop(id(execution), None)
            if maximum is None:
                maximum = visible_limit(execution)
            content = result.content
            if maximum is None or len(content) != 1 or content[0].get("type") != "text":
                return None
            text = content[0]["text"]
            if execution.name == "job_output" and not result.is_error:
                value = result.value
                body = (value["text"] or "(no new output)")
                body = body[:-1] if body.endswith("\n") else body
                suffix = "\n" + status_line(value["job"])
                if text == body + suffix:
                    return blocks(fit(body, suffix, maximum, "\n[output truncated]"))
            return blocks(fit(text, "", maximum, "\n[result truncated]"))

        def completed(snapshot, owner):
            if snapshot["reported"] or owner is None:
                return
            summary = "{} {} {}".format(snapshot["kind"], snapshot["label"], status_line(snapshot))
            summary = summary if len(summary) <= 120 else summary[:119] + "…"
            message = create_user_message({"content": blocks(completion_notice(snapshot)), "source": {
                "kind": "plugin", "plugin": "tool-jobs", "form": "notice", "summary": summary}})
            count = spent.get(owner, 0)
            if delivery == "wakeup" and owner.status == "idle" and count < budget:
                spent[owner] = count + 1
                owner.followup(message)
            else:
                owner.inject(message)
        jobs.attach_controller("tool-jobs")
        jobs.on_job_done(completed)
        ctx.get("systemPrompt").section({"name": "tool:jobs", "order": 106, "text": SYSTEM_PROMPT_JOBS_TEXT})

        def identifier(args):
            value = args["job_id"]
            if not value:
                raise ValueError("invalid job_id: expected a non-empty string")
            return value

        async def output(args, execution):
            job_id = identifier(args)
            if args.get("wait"):
                await jobs.wait(job_id, min(args.get("timeout_ms", default), cap), execution.agent, execution.signal)
            read = jobs.read(job_id, execution.agent)
            return {"text": read["text"], "job": public_job(read["snapshot"])}

        async def listing(args, execution):
            return [public_job(snapshot) for snapshot in jobs.list(execution.agent)]

        async def kill(args, execution):
            job_id = identifier(args)
            outcome = jobs.kill(job_id, execution.agent, args.get("reason"))
            return {"outcome": "already-finished" if outcome == "already-finished" else "cancellation-requested",
                    "job": public_job(jobs.get(job_id, execution.agent))}

        def output_render(args, value):
            body = value["text"] or "(no new output)"
            return blocks(body + ("" if body.endswith("\n") else "\n") + status_line(value["job"]))

        common = {"job_id": {"type": "string"}}
        definitions = [
            ("job_output", "Read a background job; wait only when blocked on completion.",
             dict(common, wait={"type": "boolean"}, timeout_ms={"type": "number"}), ["job_id"], output,
             {"type": "object", "additionalProperties": False, "properties": {"text": {"type": "string"}, "job": PUBLIC_SCHEMA}, "required": ["text", "job"]}, output_render),
            ("job_list", "List your background jobs, including finished jobs.", {}, [], listing,
             {"type": "array", "items": PUBLIC_SCHEMA},
             lambda args, value: blocks("\n".join("{id} [{kind}] {status} — {label}".format(**j) for j in value) or "(no background jobs)")),
            ("job_kill", "Request cancellation; a job settles when its work actually stops.", dict(common, reason={"type": "string"}), ["job_id"], kill,
             {"type": "object", "additionalProperties": False, "properties": {"outcome": {"type": "string", "enum": ["already-finished", "cancellation-requested"]}, "job": PUBLIC_SCHEMA}, "required": ["outcome", "job"]},
             lambda args, value: blocks("job {} had already finished {}".format(value["job"]["id"], status_line(value["job"])) if value["outcome"] == "already-finished" else "requested cancellation of job " + value["job"]["id"])),
        ]
        for name, description, properties, required, execute, schema, render in definitions:
            ctx.get("tools").register({"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                "execute": execute, "output": {"schema": schema, "render": render},
                "finalizeContent": finalize,
                "presentCall": lambda args, tool=name: {"card": "generic", "title": tool, "kind": "execute" if tool == "job_kill" else "read", "rawInput": args.get("job_id", "")}})
