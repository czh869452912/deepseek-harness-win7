from typing import Any, List, Optional

GROUNDING = (
    "Report only what earlier rounds and tool results in this session actually establish; "
    "when a detail is not in the session, say so instead of inventing it. "
)


def render_wrapup_context(objective: str, blocked_reason: Optional[str] = None) -> str:
    """Render wrapup user notice after goal completion or block."""
    heading = f"Objective: {objective}\n"
    if blocked_reason:
        return (
            "<goal_blocked>\n"
            + heading
            + f"Blocked: {blocked_reason}\n"
            + "The goal is marked blocked and this autonomous run is ending. Write the closing "
            + "message to the user now: state what has been completed so far, describe the concrete "
            + "blocking condition and what you tried, and say exactly what you need from the user to "
            + "continue. "
            + GROUNDING
            + "Address the user directly. Do not call any more tools in this run; further work "
            + "waits for the user's next instruction.\n"
            + "</goal_blocked>"
        )
    return (
        "<goal_complete>\n"
        + heading
        + "The goal is marked complete and this autonomous run is ending. Write the closing "
        + "message to the user now: state the outcome, summarize what was done and how it was "
        + "verified, and point to the concrete results (files, commits, or other artifacts). "
        + GROUNDING
        + "Note anything the user should review or do next. Address the user directly. Do not "
        + "call any more tools in this run; further work waits for the user's next instruction.\n"
        + "</goal_complete>"
    )
