"""
Host loader entry for the browser general-settings implementation.

Port of reference/packages/client/ui-settings-general/src/index.ts.
"""

from typing import Any

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import z
from dsh.settings.types import settings_namespace

# Durable settings namespace for product-wide GUI onboarding facts.
ONBOARDING_SETTINGS_NAMESPACE = "ui-onboarding"

# Durable GUI-onboarding schema: the welcome step acknowledges a version string.
OnboardingSettingsSchema = z.object(
    {
        "welcomeNoticeVersion": z.string(),
    }
)


class ClientUiSettingsGeneralPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-ui-settings-general`: registers the durable
    GUI-onboarding section when a settings provider exists.
    """

    id = "@deepseek-ai/dsh-client-ui-settings-general"
    name = "@deepseek-ai/dsh-client-ui-settings-general"

    def apply(self, ctx: Any) -> None:
        def _register(settings_ctx: Any) -> None:
            settings_ctx.get("settings").register(
                settings_namespace(ONBOARDING_SETTINGS_NAMESPACE), OnboardingSettingsSchema
            )

        ctx.inject(["settings"], _register)
