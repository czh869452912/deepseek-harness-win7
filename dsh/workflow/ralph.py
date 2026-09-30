"""Reviewed native translation of the pinned deployment-owned Ralph script."""

from pathlib import Path

from .text import js_trim, json_text, utf16_length, utf16_slice
from .workflow_service import safe_integer

RALPH_SCRIPT = Path(__file__).with_name("ralph_script.js").read_text(encoding="utf-8")
RALPH_META = dict(name="ralph-loop",
                  description="Iterate toward one objective with a fresh child and bounded structured handoff per round.",
                  phases=[dict(title="Fresh-agent rounds", detail="One clean child context per Ralph round.")])
REPORT_SCHEMA = dict(type="object", properties=dict(
    status=dict(type="string", enum=["continue", "complete", "blocked"]),
    summary=dict(type="string"), evidence=dict(type="array", items=dict(type="string")),
    nextSteps=dict(type="array", items=dict(type="string")), blocker=dict(type="string")),
    required=["status", "summary", "evidence", "nextSteps", "blocker"], additionalProperties=False)


def normalized_text(value):
    return type(value) is str and bool(value) and value == js_trim(value)


def normalized_list(value):
    return type(value) is list and all(normalized_text(item) for item in value)


def validate_report(report, max_chars):
    if type(report) is not dict:
        raise ValueError("Ralph child returned no structured round report")
    if not normalized_text(report.get("summary")):
        raise ValueError("Ralph round report summary must be non-empty and normalized")
    if not normalized_list(report.get("evidence")) or not normalized_list(report.get("nextSteps")):
        raise ValueError("Ralph round report evidence and nextSteps must contain only non-empty normalized strings")
    if type(report.get("blocker")) is not str or report["blocker"] != js_trim(report["blocker"]):
        raise ValueError("Ralph round report blocker must be a normalized string")
    status = report.get("status")
    if status == "continue":
        if not report["nextSteps"] or report["blocker"]:
            raise ValueError("a continuing Ralph report needs nextSteps and an empty blocker")
    elif status == "complete":
        if not report["evidence"] or report["nextSteps"] or report["blocker"]:
            raise ValueError("a complete Ralph report needs evidence, no nextSteps, and an empty blocker")
    elif status == "blocked":
        if not normalized_text(report["blocker"]):
            raise ValueError("a blocked Ralph report needs a concrete blocker")
    else:
        raise ValueError("Ralph round report status is invalid")
    length = utf16_length(json_text(report))
    if length > max_chars:
        raise ValueError("Ralph round report exceeds maxHandoffChars ({} > {})".format(length, max_chars))
    return report


async def execute_ralph(run):
    args, previous = run.args, None
    run.phase("Fresh-agent rounds")
    for number in range(1, args["maxRounds"] + 1):
        prior = "(none \u2014 this is the first round)" if previous is None else json_text(previous)
        prompt = "\n\n".join([
            "You are one fresh worker in a foreground Ralph loop. You receive no parent conversation and no prior child session. Do not call the ralph tool: this round already is its worker.",
            "Immutable objective:\n" + args["objective"],
            "Ralph round: {} of {}.".format(number, args["maxRounds"]),
            "The shared workspace and its current working tree are the long-term memory and source of truth. Inspect them before acting, preserve existing work, perform concrete in-scope work, and verify what you change. Treat the previous report only as a bounded handoff; confirm it against the workspace.",
            "Previous structured handoff:\n" + prior,
            "Return one report with exact normalized strings. Use status continue with at least one nextSteps entry while useful work remains; complete only with concrete evidence and no nextSteps; blocked only when no meaningful progress is possible without human input or an external-state change. blocker must be empty unless blocked.",
        ])
        raw = await run.agent(prompt, dict(label="Ralph round " + str(number), phase="Fresh-agent rounds", schema=REPORT_SCHEMA))
        if raw is None:
            return dict(status="round-failed", roundsStarted=number, lastReport=previous)
        report = validate_report(raw, args["maxHandoffChars"])
        if report["status"] in ("complete", "blocked"):
            return dict(status=report["status"], roundsStarted=number, report=report)
        previous = report
    return dict(status="budget-limited", roundsStarted=args["maxRounds"], report=previous)


def read_report(value, status, max_chars):
    if (type(value) is not dict or set(value) != {"status", "summary", "evidence", "nextSteps", "blocker"}
            or value["status"] != status or not normalized_text(value["summary"])
            or not normalized_list(value["evidence"]) or not normalized_list(value["nextSteps"])
            or type(value["blocker"]) is not str or value["blocker"] != js_trim(value["blocker"])):
        raise ValueError("Ralph workflow returned a malformed round report")
    report = {key: value[key] for key in ("status", "summary", "evidence", "nextSteps", "blocker")}
    if status == "continue" and (not report["nextSteps"] or report["blocker"]):
        raise ValueError("Ralph workflow returned an invalid continuing report")
    if status == "complete" and (not report["evidence"] or report["nextSteps"] or report["blocker"]):
        raise ValueError("Ralph workflow returned an invalid completion report")
    if status == "blocked" and not normalized_text(report["blocker"]):
        raise ValueError("Ralph workflow returned an invalid blocked report")
    length = utf16_length(json_text(report))
    if length > max_chars:
        raise ValueError("Ralph workflow returned an oversized handoff ({} > {})".format(length, max_chars))
    return report


def read_result(value, max_rounds, max_chars):
    if type(value) is not dict or not safe_integer(value.get("roundsStarted")) or value["roundsStarted"] > max_rounds:
        raise ValueError("Ralph workflow returned a malformed terminal result")
    rounds, status = int(value["roundsStarted"]), value.get("status")
    if status in ("complete", "blocked", "budget-limited"):
        if set(value) != {"report", "roundsStarted", "status"}:
            raise ValueError("Ralph workflow returned a malformed terminal result")
        if status == "budget-limited" and rounds != max_rounds:
            raise ValueError("Ralph workflow returned budget-limited before the round limit")
        return dict(status=status, roundsStarted=rounds,
                    report=read_report(value["report"], "continue" if status == "budget-limited" else status, max_chars))
    if status == "round-failed":
        if set(value) != {"lastReport", "roundsStarted", "status"}:
            raise ValueError("Ralph workflow returned a malformed terminal result")
        result = dict(status=status, roundsStarted=rounds)
        if rounds == 1:
            if value["lastReport"] is not None:
                raise ValueError("Ralph workflow returned an invalid first-round failure")
        else:
            if value["lastReport"] is None:
                raise ValueError("Ralph workflow returned a round failure without its last handoff")
            result["lastReport"] = read_report(value["lastReport"], "continue", max_chars)
        return result
    raise ValueError("Ralph workflow returned an unknown terminal status")


def bound_result(text, max_chars):
    notice = "\n\u2026 [truncated]"
    if utf16_length(text) <= max_chars:
        return text
    if max_chars <= utf16_length(notice):
        return utf16_slice(notice, max_chars)
    return utf16_slice(text, max_chars - utf16_length(notice)) + notice


def render_result(result, max_chars):
    rounds = "{} round{}".format(result["roundsStarted"], "" if result["roundsStarted"] == 1 else "s")
    status = result["status"]
    if status == "complete":
        text = "Ralph worker reported completion after {}.".format(rounds)
    elif status == "blocked":
        text = "Ralph worker reported a blocker after {}.".format(rounds)
    elif status == "budget-limited":
        text = "Ralph reached its {} limit; the worker reported work remaining.".format(rounds)
    else:
        text = "Ralph round {} child failed before producing a structured report.".format(result["roundsStarted"])
        text += ("\nLast successful handoff:\n" + json_text(result["lastReport"], True)
                 if "lastReport" in result else "\nNo previous handoff was available.")
        return bound_result(text, max_chars)
    return bound_result(text + "\nFinal report:\n" + json_text(result["report"], True), max_chars)
