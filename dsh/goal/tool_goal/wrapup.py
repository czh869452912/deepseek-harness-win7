from typing import Optional


def render_wrapup_context(objective: str, blocked_reason: Optional[str] = None) -> str:
    """Render wrapup user notice after goal completion or block."""
    if blocked_reason:
        return (
            f"The goal '{objective}' was marked blocked: {blocked_reason}. "
            "Summarize the work done, the blocking condition, and any recommendations for the user."
        )
    return (
        f"The goal '{objective}' is complete. "
        "Summarize what was accomplished and any next steps for the user."
    )
