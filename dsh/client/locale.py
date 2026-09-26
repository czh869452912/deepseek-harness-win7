"""
Host registration for the browser locale preference.

Port of reference/packages/client/locale/src/index.ts plus its
`locale-settings.ts` section definition.
"""

import re
from typing import Any

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import z
from dsh.settings.types import settings_namespace

# Settings namespace owned by the locale plugin.
LOCALE_SETTINGS_NAMESPACE = "locale"

# Field carrying an explicit locale selection; absence delegates to the browser.
LOCALE_PREFERENCE_FIELD = "preference"

# Accepted BCP 47-style language ids.
LOCALE_ID_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")

# Locale identifiers shipped by the browser client.
LOCALE_IDS = ("zh", "en")

# Durable locale schema; also the wire envelope the browser scope validates against.
LocaleSettingsSchema = z.object(
    {
        LOCALE_PREFERENCE_FIELD: z.string().pattern(LOCALE_ID_PATTERN).required(False),
    }
)


class ClientLocalePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-locale`: registers the durable locale
    section when a settings provider exists.
    """

    id = "@deepseek-ai/dsh-client-locale"
    name = "@deepseek-ai/dsh-client-locale"

    def apply(self, ctx: Any) -> None:
        def _register(settings_ctx: Any) -> None:
            settings_ctx.get("settings").register(
                settings_namespace(LOCALE_SETTINGS_NAMESPACE), LocaleSettingsSchema
            )

        ctx.inject(["settings"], _register)
