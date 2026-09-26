"""
Host registration for the browser theme preference and pre-plugin palette.

Port of reference/packages/client/ui-theme/src/index.ts plus its
`theme-settings.ts` and `boot-theme.ts` definitions.
"""

import json
from typing import Any, Dict

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import z
from dsh.settings.types import settings_namespace

# Built-in preferences accepted at the registry and settings boundaries.
THEME_PREFERENCES = ("light", "dark", "system")

# Settings namespace owned by the theme plugin.
THEME_SETTINGS_NAMESPACE = "ui-theme"

# Field carrying the selected built-in theme preference.
THEME_PREFERENCE_FIELD = "preference"

# Field carrying the conversation content font size.
FONT_SIZE_FIELD = "fontSize"

# Default preference when the user-settings document has no override.
DEFAULT_PREFERENCE = "system"

# Smallest accepted content font size (px).
FONT_SIZE_MIN = 12

# Largest accepted content font size (px).
FONT_SIZE_MAX = 17

# Content font size when the user-settings document has no override (px).
DEFAULT_FONT_SIZE = 14

# Durable theme schema; also the wire envelope the browser scope validates against.
ThemeSettingsSchema = z.object(
    {
        THEME_PREFERENCE_FIELD: z.union(list(THEME_PREFERENCES)).default(DEFAULT_PREFERENCE),
        FONT_SIZE_FIELD: z.number()
        .step(1)
        .min(FONT_SIZE_MIN)
        .max(FONT_SIZE_MAX)
        .default(DEFAULT_FONT_SIZE),
    }
)

THEME_NAMESPACE = settings_namespace(THEME_SETTINGS_NAMESPACE)


def is_theme_preference(value: Any) -> bool:
    """
    Narrow one wire or registry value to a persistable preference.

    @param value: value crossing the settings or registry boundary.
    @returns: whether the value is a built-in preference.
    """
    return any(preference == value for preference in THEME_PREFERENCES)


def boot_theme_script(preference: str, font_size: int) -> str:
    """
    Build the inline script body for one schema-validated durable theme section.

    @param preference: current Host-backed built-in preference.
    @param font_size: current Host-backed content font size in px.
    @returns: the script body the browser runs before the shell mount.
    """
    return (
        "(() => {\n"
        "  const preference = %s\n" % json.dumps(preference)
        + "  const systemDark = preference === 'system'\n"
        "    && typeof matchMedia !== 'undefined'\n"
        "    && matchMedia('(prefers-color-scheme: dark)').matches\n"
        "  const dark = preference === 'dark' || systemDark\n"
        "  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'\n"
        "  document.body.toggleAttribute('data-ds-dark-theme', dark)\n"
        "  document.body.style.setProperty('--dsh-content-font-size', %s)\n"
        "})()" % json.dumps("%dpx" % font_size)
    )


def boot_theme_injection(preference: str = DEFAULT_PREFERENCE, font_size: int = DEFAULT_FONT_SIZE) -> Dict[str, Any]:
    """
    The theme bootstrap as an injection row: an inline script immediately after
    the opening body tag, before the shell mount and module script.

    @param preference: current Host-backed built-in preference.
    @param font_size: current Host-backed content font size in px.
    @returns: the body script row.
    """
    return {"kind": "script", "placement": "body", "text": boot_theme_script(preference, font_size)}


def read_section(ctx: Any) -> Dict[str, Any]:
    """
    Read the registered theme section or the schema defaults without a settings provider.

    @param ctx: host context that may carry the settings service.
    @returns: the current preference and content font size.
    """
    fallback = {THEME_PREFERENCE_FIELD: DEFAULT_PREFERENCE, FONT_SIZE_FIELD: DEFAULT_FONT_SIZE}
    settings = ctx.get("settings")
    if settings is None:
        return fallback
    section = settings.get(THEME_NAMESPACE)
    if section is None:
        return fallback
    return section


class ClientUiThemePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-ui-theme`: registers the durable theme
    section when the optional settings service is composed, and answers every
    index injection collection with the current theme bootstrap row.
    """

    id = "@deepseek-ai/dsh-client-ui-theme"
    name = "@deepseek-ai/dsh-client-ui-theme"

    def apply(self, ctx: Any) -> None:
        def _register(settings_ctx: Any) -> None:
            settings_ctx.get("settings").register(THEME_NAMESPACE, ThemeSettingsSchema)

        ctx.inject(["settings"], _register)

        def _on_index_inject(table: Any) -> None:
            section = read_section(ctx)
            table.append(
                boot_theme_injection(section.get(THEME_PREFERENCE_FIELD), section.get(FONT_SIZE_FIELD))
            )

        ctx.on("webserver/index-inject", _on_index_inject)
