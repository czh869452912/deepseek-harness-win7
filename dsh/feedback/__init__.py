"""
Feedback producers (`@deepseek-ai/dsh-command-feedback` and
`@deepseek-ai/dsh-message-feedback`).
"""

from dsh.feedback.command_feedback import (
    CommandFeedbackPlugin,
    execute_feedback_command,
    record_feedback,
    sharing_disclosure,
    sharing_sentence,
)
from dsh.feedback.invariant import apply as apply_command_feedback_invariant

__all__ = [
    "CommandFeedbackPlugin",
    "apply_command_feedback_invariant",
    "execute_feedback_command",
    "record_feedback",
    "sharing_disclosure",
    "sharing_sentence",
]
