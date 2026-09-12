"""
Session feedback event plus the human-facing `/feedback` producer.
1:1 with reference/packages/feedback/command-feedback/src/index.ts.

Recording appends one authoritative log-only event and does not start model
work. The append is eager but unflushed, so acknowledgement reports that the
entry is logged, not that it reached disk.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
from typing import Any, Callable, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.identity.anonymous_user_id import get_or_create_anonymous_user_id

__all__ = [
    "USAGE",
    "apply",
    "CommandFeedbackPlugin",
    "execute_feedback_command",
    "record_feedback",
    "recordFeedback",
    "sharing_disclosure",
    "sharing_sentence",
]

#: Plugin row name this package mounts as.
name = "command-feedback"

#: Service this producer requires before it can register its command.
inject = ["commands"]

USAGE = "Usage: /feedback <text>"

#: The acknowledgement sentence for each disclosed sharing policy. A status
#: outside this closed set is a deployment bug, not a silent fallback.
_SHARING_SENTENCES: Dict[str, str] = {
    "full": "Session sharing is enabled.",
    "feedback-only": (
        "Session sharing is feedback-gated; recording feedback uploads the "
        "session records not yet shared."
    ),
    "disabled": "Session sharing is disabled.",
}


def sharing_sentence(sharing: Any) -> str:
    """
    The acknowledgement's sharing sentence for a disclosed policy.

    @param sharing: the mounted backend's disclosed sharing status.
    @returns: the sentence for that status.
    @raises RuntimeError: for a status outside the closed union.
    """
    sentence = _SHARING_SENTENCES.get(sharing) if isinstance(sharing, str) else None
    if sentence is None:
        raise RuntimeError(
            "command-feedback: unsupported sharing status {}".format(json.dumps(sharing))
        )
    return sentence


sharingSentence = sharing_sentence


def sharing_disclosure(telemetry: Any) -> str:
    """
    The sharing disclosure appended to the acknowledgement: the mounted
    backend's disclosed policy, or a "not configured" notice when no backend is
    mounted. Read through the plugin context so the command still works when the
    telemetry service is absent.

    @param telemetry: the mounted telemetry service, or `None`.
    @returns: one sentence describing this session's sharing policy.
    """
    if telemetry is None:
        return "Session sharing is not configured."
    return sharing_sentence(getattr(telemetry, "sharing", None))


sharingDisclosure = sharing_disclosure


def record_feedback(session: Any, text: str) -> None:
    """
    Record feedback independently of any UI trigger.

    @param session: session the feedback describes.
    @param text: human-authored feedback; surrounding whitespace is discarded.
    @raises TypeError: when the normalized text is empty.
    """
    normalized = text.strip()
    if len(normalized) == 0:
        raise TypeError("feedback text must not be empty")
    session.append("feedback/record", {"text": normalized})


recordFeedback = record_feedback


def _raw_input(invocation: Any) -> str:
    """The invocation's verbatim input, under either spelling."""
    for attr in ("rawInput", "raw_input"):
        value = getattr(invocation, attr, None)
        if isinstance(value, str):
            return value
    return ""


def execute_feedback_command(invocation: Any, ctx: Any) -> Dict[str, Any]:
    """
    Validate, record, and acknowledge one feedback entry. Returning an error
    leaves no `feedback/record` event.

    @param invocation: receiving agent, raw command input, and UI cancellation.
    @param ctx: plugin context used to read the optional telemetry service.
    @returns: an acknowledgement containing the receiving session and anonymous
        user ids plus the session-sharing disclosure, or a usage error when no
        feedback text was supplied.
    """
    raw = _raw_input(invocation)
    if len(raw.strip()) == 0:
        return {"kind": "error", "text": "Feedback text is required. {}".format(USAGE)}
    session = invocation.agent.session
    record_feedback(session, raw)
    telemetry = ctx.get("sessionTelemetry") if hasattr(ctx, "get") else None
    return {
        "kind": "success",
        "text": "Feedback recorded for session {}\nAnonymous user: {}. {}".format(
            session.id, get_or_create_anonymous_user_id(), sharing_disclosure(telemetry)
        ),
    }


executeFeedbackCommand = execute_feedback_command


def apply(ctx: Any) -> Callable[[], None]:
    """
    Register the global `/feedback` command for every composed command adapter.

    @param ctx: the context whose `commands` service receives the definition.
    @returns: the exact effect disposer that unregisters the command.
    """
    commands = ctx.get("commands") if hasattr(ctx, "get") else None
    if commands is None or not hasattr(commands, "register"):
        raise RuntimeError("command-feedback: the commands service is not mounted")
    return commands.register(
        {
            "name": "feedback",
            "description": "record feedback about this session",
            "input": {"hint": "<text>"},
            "recordInput": False,
            "handler": lambda invocation: execute_feedback_command(invocation, ctx),
        }
    )


class CommandFeedbackPlugin(Plugin):
    """
    Plugin row `@deepseek-ai/dsh-command-feedback`: the module-level producer,
    mounted as the installation-owned row.
    """

    id = "command-feedback"
    name = "@deepseek-ai/dsh-command-feedback"
    inject = ["commands"]

    def apply(self, ctx: Any) -> None:
        apply(ctx)
