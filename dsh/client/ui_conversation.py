"""
Host registration for browser conversation preferences.

Port of reference/packages/client/ui-conversation/src/index.ts plus its
`submission-settings.ts` section definition.
"""

from typing import Any

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import z
from dsh.settings.types import settings_namespace

# Settings namespace owned by the conversation plugin.
CONVERSATION_SETTINGS_NAMESPACE = "ui-conversation"

# Field carrying the delivery mode for plain Enter while an agent is busy.
BUSY_ENTER_FIELD = "busyEnter"

# Busy-Enter behaviors accepted at settings and input boundaries.
BUSY_ENTER_BEHAVIORS = ("queue", "steer")

# Default preserves Enter-as-Queue for running conversations.
DEFAULT_BUSY_ENTER_BEHAVIOR = "queue"

# Durable conversation schema; also the wire envelope the browser scope validates against.
ConversationSettingsSchema = z.object(
    {
        BUSY_ENTER_FIELD: z.union(list(BUSY_ENTER_BEHAVIORS)).default(DEFAULT_BUSY_ENTER_BEHAVIOR),
    }
)


class ClientUiConversationPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-ui-conversation`: registers the durable
    conversation section when a provider exists.
    """

    id = "@deepseek-ai/dsh-client-ui-conversation"
    name = "@deepseek-ai/dsh-client-ui-conversation"

    def apply(self, ctx: Any) -> None:
        def _register(settings_ctx: Any) -> None:
            settings_ctx.get("settings").register(
                settings_namespace(CONVERSATION_SETTINGS_NAMESPACE), ConversationSettingsSchema
            )

        ctx.inject(["settings"], _register)
