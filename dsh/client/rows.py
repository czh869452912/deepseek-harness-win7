"""
The installation-owned Loader rows for the browser client packages.

Every `dsh.client` row the shipped bundle patches enable (`packages/bundle/*/
cordis.patch.yml`) has a host half: a Cordis plugin that mounts in the host
tree, so the modules node half finds the package's `dsh.client` declaration and
serves its `./client` bundle to the browser. This module is the row name ->
implementation mapping those rows resolve through.

Rows whose host half is an empty `apply` (upstream's pure UI plugins) come from
`dsh/client/surfaces.py`; the settings-backed and prompt-section rows come from
their own modules. `@deepseek-ai/dsh-client-connection` and
`@deepseek-ai/dsh-client-hmr` carry real host transport/reload behavior and are
not implemented yet, so they stay out of this table.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Dict

from dsh.client.surfaces import EMPTY_HOST_HALVES

__all__ = ["CLIENT_HOST_HALF_ROWS"]


# Row name -> 'module:Class' spec, one per browser client package the
# installation implements.
CLIENT_HOST_HALF_ROWS: Dict[str, str] = {
    package_name: "dsh.client.surfaces:%s" % class_name
    for class_name, (package_name, _upstream) in EMPTY_HOST_HALVES.items()
}

CLIENT_HOST_HALF_ROWS.update(
    {
        "@deepseek-ai/dsh-client-locale": "dsh.client.locale:ClientLocalePlugin",
        "@deepseek-ai/dsh-client-ui-chat": "dsh.client.ui_chat:ClientUiChatPlugin",
        "@deepseek-ai/dsh-client-ui-conversation": "dsh.client.ui_conversation:ClientUiConversationPlugin",
        "@deepseek-ai/dsh-client-ui-deliverables": "dsh.client.ui_deliverables:ClientUiDeliverablesPlugin",
        "@deepseek-ai/dsh-client-ui-settings-general": "dsh.client.ui_settings_general:ClientUiSettingsGeneralPlugin",
        "@deepseek-ai/dsh-client-ui-theme": "dsh.client.ui_theme:ClientUiThemePlugin",
    }
)
