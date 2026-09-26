"""
Host registration for browser Chat preferences.

Port of reference/packages/client/ui-chat/src/index.ts plus its
`chat-settings.ts` section definition.
"""

from typing import Any

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import z
from dsh.settings.types import settings_namespace

# Settings namespace owned by the Chat target.
CHAT_SETTINGS_NAMESPACE = "ui-chat"

# Field carrying the completed-Turn transcript presentation mode.
TRANSCRIPT_VIEW_FIELD = "transcriptView"

# Transcript presentation modes accepted at settings boundaries.
TRANSCRIPT_VIEW_MODES = ("normal", "compact")

# Default preserves the compact process disclosure introduced by Chat.
DEFAULT_TRANSCRIPT_VIEW_MODE = "compact"

# Durable Chat schema; also the wire envelope the browser scope validates against.
ChatSettingsSchema = z.object(
    {
        TRANSCRIPT_VIEW_FIELD: z.union(list(TRANSCRIPT_VIEW_MODES)).default(DEFAULT_TRANSCRIPT_VIEW_MODE),
    }
)


class ClientUiChatPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-ui-chat`: registers the durable Chat
    settings section when a provider exists.
    """

    id = "@deepseek-ai/dsh-client-ui-chat"
    name = "@deepseek-ai/dsh-client-ui-chat"

    def apply(self, ctx: Any) -> None:
        def _register(settings_ctx: Any) -> None:
            settings_ctx.get("settings").register(
                settings_namespace(CHAT_SETTINGS_NAMESPACE), ChatSettingsSchema
            )

        ctx.inject(["settings"], _register)
