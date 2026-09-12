"""
`@deepseek-ai/dsh-message-feedback`: durable, lifecycle-bound feedback for
finalized assistant messages (Windows 7 / Python 3.8 port).
"""

from dsh.feedback.message_feedback import (
    MessageFeedback,
    MessageFeedbackPlugin,
    MessageFeedbackService,
    resolve_max_note_bytes,
)
from dsh.feedback.message_feedback_spec import (
    message_feedback_domain_spec,
    message_feedback_item_schema,
    message_feedback_rating_schema,
    message_feedback_row_schema,
    message_feedback_session_identity_schema,
    message_feedback_version_schema,
)

messageFeedbackDomainSpec = message_feedback_domain_spec
messageFeedbackItemSchema = message_feedback_item_schema
messageFeedbackRatingSchema = message_feedback_rating_schema
messageFeedbackRowSchema = message_feedback_row_schema
messageFeedbackSessionIdentitySchema = message_feedback_session_identity_schema
messageFeedbackVersionSchema = message_feedback_version_schema
MessageFeedbackDomainSpec = message_feedback_domain_spec

__all__ = [
    "MessageFeedback",
    "MessageFeedbackDomainSpec",
    "MessageFeedbackPlugin",
    "MessageFeedbackService",
    "messageFeedbackDomainSpec",
    "messageFeedbackItemSchema",
    "messageFeedbackRatingSchema",
    "messageFeedbackRowSchema",
    "messageFeedbackSessionIdentitySchema",
    "messageFeedbackVersionSchema",
    "message_feedback_domain_spec",
    "message_feedback_item_schema",
    "message_feedback_rating_schema",
    "message_feedback_row_schema",
    "message_feedback_session_identity_schema",
    "message_feedback_version_schema",
    "resolve_max_note_bytes",
]
